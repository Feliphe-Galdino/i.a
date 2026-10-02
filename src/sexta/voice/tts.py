"""Fala local pelo Windows (SAPI) — vozes já instaladas, gratuitas e offline.

1. ``SapiSpeaker``: usa o SAPI via ``pywin32`` (rápido, interrompível).
2. ``PowerShellSpeaker``: alternativa sem dependências (System.Speech do .NET).
3. ``NullSpeaker``: fora do Windows (desenvolvimento/testes) — só registra no log.

Para ter a voz em português, o Windows precisa do pacote de fala pt-BR
(Configurações → Hora e idioma → Fala → Adicionar vozes → Português (Brasil)).
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

Done = Callable[[], None]


class Speaker(Protocol):
    name: str

    def say(self, text: str, on_done: Done | None = None) -> None: ...
    def stop(self) -> None: ...
    def voices(self) -> list[str]: ...
    def configure(self, *, voice: str = "", rate: int = 1) -> None: ...
    def close(self) -> None: ...


class NullSpeaker:
    name = "nenhuma"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def say(self, text: str, on_done: Done | None = None) -> None:
        log.info("[fala] %s", text)
        self.spoken.append(text)
        if on_done:
            on_done()

    def stop(self) -> None:
        pass

    def voices(self) -> list[str]:
        return []

    def configure(self, *, voice: str = "", rate: int = 1) -> None:
        pass

    def close(self) -> None:
        pass


def _pick(voices: list[str], wanted: str) -> str | None:
    if wanted:
        for name in voices:
            if wanted.lower() in name.lower():
                return name
    for hint in ("portuguese", "português", "brazil", "brasil", "maria", "daniel", "francisca"):
        for name in voices:
            if hint in name.lower():
                return name
    return None


class SapiSpeaker:
    """SAPI 5 via COM, numa thread própria (o COM exige isso)."""

    name = "Windows SAPI"

    def __init__(self, *, voice: str = "", rate: int = 1):
        import win32com.client  # type: ignore[import-not-found]  # noqa: F401 — falha cedo se ausente

        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._config = {"voice": voice, "rate": rate}
        self._dirty = True
        self._thread = threading.Thread(target=self._run, name="sexta-tts", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        engine = win32com.client.Dispatch("SAPI.SpVoice")
        while True:
            item = self._queue.get()
            if item is None:
                break
            text, on_done = item
            try:
                if self._dirty:
                    self._apply(engine)
                self._stop.clear()
                engine.Speak(text, 1)  # SVSFlagsAsync
                while not engine.WaitUntilDone(100):
                    if self._stop.is_set():
                        engine.Speak("", 3)  # assíncrono + limpa a fila
                        break
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha na fala SAPI: %s", exc)
            finally:
                if on_done:
                    on_done()

    def _apply(self, engine) -> None:
        tokens = engine.GetVoices()
        names = [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
        chosen = _pick(names, self._config["voice"])
        if chosen:
            engine.Voice = tokens.Item(names.index(chosen))
        engine.Rate = max(-10, min(10, int(self._config["rate"])))
        engine.Volume = 100
        self._dirty = False

    def say(self, text: str, on_done: Done | None = None) -> None:
        self._queue.put((text, on_done))

    def stop(self) -> None:
        self._stop.set()

    def voices(self) -> list[str]:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        tokens = win32com.client.Dispatch("SAPI.SpVoice").GetVoices()
        return [tokens.Item(i).GetDescription() for i in range(tokens.Count)]

    def configure(self, *, voice: str = "", rate: int = 1) -> None:
        self._config = {"voice": voice, "rate": rate}
        self._dirty = True

    def close(self) -> None:
        self.stop()
        self._queue.put(None)


_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "if ($env:SEXTA_VOICE) { try { $s.SelectVoice($env:SEXTA_VOICE) } catch {} };"
    "$s.Rate = [int]$env:SEXTA_RATE;"
    "$t = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:SEXTA_TEXT));"
    "$s.Speak($t)"
)


class PowerShellSpeaker:
    """Alternativa sem pywin32: um processo PowerShell por fala (interrompível)."""

    name = "Windows (PowerShell)"

    def __init__(self, *, voice: str = "", rate: int = 1):
        self._voice = voice
        self._rate = rate
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _flags(self) -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def say(self, text: str, on_done: Done | None = None) -> None:
        def run() -> None:
            env = {
                **os.environ,
                "SEXTA_TEXT": base64.b64encode(text.encode("utf-8")).decode(),
                "SEXTA_RATE": str(max(-10, min(10, self._rate))),
                "SEXTA_VOICE": _pick(self.voices(), self._voice) or "",
            }
            try:
                with self._lock:
                    self._proc = subprocess.Popen(  # noqa: S603
                        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=self._flags(),
                    )
                self._proc.wait()
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha na fala via PowerShell: %s", exc)
            finally:
                if on_done:
                    on_done()

        threading.Thread(target=run, name="sexta-tts-ps", daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()

    def voices(self) -> list[str]:
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | "
            "% { $_.VoiceInfo.Name }"
        )
        try:
            out = subprocess.run(  # noqa: S603
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=self._flags(),
            )
            return [line.strip() for line in out.stdout.splitlines() if line.strip()]
        except Exception:  # noqa: BLE001
            return []

    def configure(self, *, voice: str = "", rate: int = 1) -> None:
        self._voice, self._rate = voice, rate

    def close(self) -> None:
        self.stop()


def build_speaker(*, voice: str = "", rate: int = 1) -> Speaker:
    if sys.platform != "win32":
        return NullSpeaker()
    try:
        return SapiSpeaker(voice=voice, rate=rate)
    except Exception as exc:  # noqa: BLE001
        log.info("pywin32 indisponível (%s); usando a fala via PowerShell.", exc)
        return PowerShellSpeaker(voice=voice, rate=rate)
