"""Integração com o Windows: início automático, janela de voz e CLI (testável em qualquer SO)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TOKEN
from sexta import winsys
from sexta.__main__ import build_parser, main
from sexta.app import create_app
from sexta.container import build_sexta


class FakeRunKey:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_autostart_command_is_hidden_and_quoted():
    command = winsys.autostart_command(Path("C:/Users/Fulano de Tal/i.a"))
    assert "-m sexta serve" in command
    assert "--app-window" in command and "--headless" in command
    assert '"C:/Users/Fulano de Tal/i.a"' in command  # caminho com espaço entre aspas


def test_autostart_manager_enable_disable():
    key = FakeRunKey()
    manager = winsys.AutostartManager(Path("C:/proj"), key)
    assert manager.supported
    assert manager.status()["enabled"] is False
    status = manager.enable()
    assert status["enabled"] and status["up_to_date"]
    assert key.values[winsys.VALUE_NAME] == winsys.autostart_command(Path("C:/proj"))
    key.values[winsys.VALUE_NAME] = "comando antigo"
    assert manager.status()["up_to_date"] is False
    assert manager.disable()["enabled"] is False


@pytest.mark.skipif(winsys.is_windows(), reason="verifica o comportamento fora do Windows")
def test_autostart_unsupported_outside_windows():
    manager = winsys.AutostartManager(Path("."))
    assert not manager.supported
    with pytest.raises(RuntimeError):
        manager.enable()


def test_app_window_command_has_voice_flags(tmp_path):
    cmd = winsys.app_window_command(Path("chrome.exe"), "http://127.0.0.1:8765/?token=x", tmp_path)
    assert cmd[1] == "--app=http://127.0.0.1:8765/?token=x"
    assert f"--user-data-dir={tmp_path}" in cmd
    assert "--autoplay-policy=no-user-gesture-required" in cmd  # áudio sem clique após o boot
    assert "--disable-background-timer-throttling" in cmd  # continua ouvindo minimizada


def test_find_browser_override(tmp_path):
    fake = tmp_path / "chrome.exe"
    fake.write_text("")
    assert winsys.find_browser(str(fake)) == fake


def test_instance_running_false_on_free_port():
    assert winsys.instance_running(1, timeout=0.2) is False


def test_workdir_option_is_kept_before_subcommand():
    args = build_parser().parse_args(["--workdir", "C:/proj", "serve"])
    assert args.workdir == "C:/proj"
    args = build_parser().parse_args(["serve", "--workdir", "C:/outro", "--app-window", "--headless"])
    assert args.workdir == "C:/outro" and args.app_window and args.headless


@pytest.mark.skipif(winsys.is_windows(), reason="verifica o comportamento fora do Windows")
def test_cli_autostart_outside_windows(capsys):
    assert main(["autostart", "status"]) == 1
    assert "apenas no Windows" in capsys.readouterr().out


def test_api_autostart_and_shutdown(settings, provider):
    key = FakeRunKey()
    sexta = build_sexta(settings, provider=provider, run_key=key)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(create_app(sexta=sexta)) as client:
        assert client.get("/api/system/autostart", headers=auth).json()["enabled"] is False
        enabled = client.put("/api/system/autostart", json={"enabled": True}, headers=auth).json()
        assert enabled["enabled"] is True and winsys.VALUE_NAME in key.values
        assert client.put("/api/system/autostart", json={"enabled": False}, headers=auth).json()["enabled"] is False
        assert client.post("/api/system/shutdown", headers=auth).status_code == 503  # sem servidor uvicorn
        assert client.post("/api/system/shutdown").status_code == 401
