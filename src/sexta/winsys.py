"""Integração com o Windows 11.

* **Iniciar com o Windows**: um valor na chave ``HKCU\\...\\Run`` do *seu* usuário (não
  exige administrador). Ao entrar no Windows, o servidor sobe oculto (``pythonw``) e abre a
  janela da Sexta-Feira, já escutando as palmas e o "Olá, Sexta-Feira".
* **Janela da assistente**: Chrome (ou Edge) em modo aplicativo, com perfil próprio e
  áudio liberado sem clique — necessário para ouvir e falar logo após ligar o PC.

O código é importável em qualquer sistema (os testes rodam no Linux); as partes que
usam o registro só executam no Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SextaFeira"

BROWSER_CANDIDATES = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
]

# Flags da janela dedicada: áudio/voz sem clique e sem "adormecer" quando minimizada.
APP_WINDOW_FLAGS = [
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-features=CalculateNativeWinOcclusion",
    "--no-first-run",
    "--no-default-browser-check",
    "--hide-crash-restore-bubble",
    "--window-size=1280,860",
]


def is_windows() -> bool:
    return sys.platform == "win32"


def pythonw_executable() -> Path:
    """``pythonw.exe`` (sem janela de console) do mesmo ambiente; senão o Python atual."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def serve_command(workdir: Path, *, window: bool = True) -> list[str]:
    cmd = [str(pythonw_executable()), "-m", "sexta", "serve", "--headless", "--workdir", str(workdir)]
    if window:
        cmd.insert(4, "--app-window")
    else:
        cmd.insert(4, "--no-browser")
    return cmd


def autostart_command(workdir: Path, *, window: bool = False) -> str:
    """Por padrão, sobe só o servidor (a voz local não precisa de janela)."""
    return subprocess.list2cmdline(serve_command(workdir, window=window))


# --------------------------------------------------------------------------
# Registro (HKCU\...\Run)
# --------------------------------------------------------------------------


class RunKey(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class WinRegRunKey:
    """Acesso real ao registro do usuário atual."""

    def get(self, name: str) -> str | None:
        import winreg  # type: ignore[import-not-found]

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except FileNotFoundError:
            return None

    def set(self, name: str, value: str) -> None:
        import winreg  # type: ignore[import-not-found]

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg  # type: ignore[import-not-found]

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


@dataclass
class AutostartManager:
    workdir: Path
    run_key: RunKey | None = None

    def __post_init__(self) -> None:
        if self.run_key is None and is_windows():
            self.run_key = WinRegRunKey()

    @property
    def supported(self) -> bool:
        return self.run_key is not None

    def status(self) -> dict[str, object]:
        current = self.run_key.get(VALUE_NAME) if self.run_key else None
        window = bool(current and "--app-window" in current)
        expected = autostart_command(self.workdir, window=window)
        return {
            "supported": self.supported,
            "enabled": current is not None,
            "window": window,
            "up_to_date": current == expected,
            "command": current or expected,
        }

    def enable(self, *, window: bool = False) -> dict[str, object]:
        if not self.run_key:
            raise RuntimeError("Iniciar com o sistema está disponível apenas no Windows.")
        self.run_key.set(VALUE_NAME, autostart_command(self.workdir, window=window))
        return self.status()

    def disable(self) -> dict[str, object]:
        if not self.run_key:
            raise RuntimeError("Iniciar com o sistema está disponível apenas no Windows.")
        self.run_key.delete(VALUE_NAME)
        return self.status()


# --------------------------------------------------------------------------
# Janela da assistente e instância única
# --------------------------------------------------------------------------


def find_browser(override: str | None = None) -> Path | None:
    candidates = [override] if override else []
    candidates += BROWSER_CANDIDATES
    for raw in candidates:
        if not raw:
            continue
        path = Path(os.path.expandvars(raw))
        if path.is_file():
            return path
    return None


def app_window_command(browser: Path, url: str, profile_dir: Path) -> list[str]:
    return [str(browser), f"--app={url}", f"--user-data-dir={profile_dir}", *APP_WINDOW_FLAGS]


def open_app_window(url: str, *, profile_dir: Path, browser_override: str | None = None) -> str:
    """Abre a janela dedicada (Chrome/Edge). Fora do Windows, usa o navegador padrão."""
    browser = find_browser(browser_override) if is_windows() or browser_override else None
    if browser is None:
        webbrowser.open(url)
        return "navegador padrão"
    profile_dir.mkdir(parents=True, exist_ok=True)
    flags = 0
    if is_windows():
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen(  # noqa: S603 — comando montado por nós, sem shell
        app_window_command(browser, url, profile_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return browser.name


def instance_running(port: int, *, timeout: float = 1.0) -> bool:
    """Verifica se já há uma Sexta-Feira respondendo nesta porta."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode()).get("name") == "Sexta-Feira"
    except Exception:  # noqa: BLE001 — qualquer falha = não está rodando
        return False


def spawn_background_server(workdir: Path) -> None:
    """Sobe o servidor oculto e desacoplado deste terminal."""
    flags = 0
    if is_windows():
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen(  # noqa: S603
        serve_command(workdir),
        cwd=str(workdir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
        start_new_session=not is_windows(),
    )
