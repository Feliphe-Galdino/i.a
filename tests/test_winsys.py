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
    assert "--headless" in command and "--no-browser" in command  # voz local: sem janela
    assert '"C:/Users/Fulano de Tal/i.a"' in command  # caminho com espaço entre aspas
    with_window = winsys.autostart_command(Path("C:/proj"), window=True)
    assert "--app-window" in with_window and "--no-browser" not in with_window


def test_autostart_manager_enable_disable():
    key = FakeRunKey()
    manager = winsys.AutostartManager(Path("C:/proj"), key)
    assert manager.supported
    assert manager.status()["enabled"] is False
    status = manager.enable()
    assert status["enabled"] and status["up_to_date"] and not status["window"]
    assert key.values[winsys.VALUE_NAME] == winsys.autostart_command(Path("C:/proj"))
    assert manager.enable(window=True)["window"] is True
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


# --- Diagnóstico e configuração da chave -------------------------------------------------

FAKE_KEY = "sk-ant-api03-" + "x" * 40


def test_write_env_key_creates_from_example_and_replaces(tmp_path):
    from sexta.__main__ import write_env_key

    (tmp_path / ".env.example").write_text("# comentário\nANTHROPIC_API_KEY=\nSEXTA_PORT=8765\n", encoding="utf-8")
    env = tmp_path / ".env"
    write_env_key(env, FAKE_KEY)
    assert env.read_text(encoding="utf-8") == f"# comentário\nANTHROPIC_API_KEY={FAKE_KEY}\nSEXTA_PORT=8765\n"
    write_env_key(env, FAKE_KEY.replace("x", "y"))  # troca a chave sem duplicar a linha
    text = env.read_text(encoding="utf-8")
    assert text.count("ANTHROPIC_API_KEY=") == 1 and "y" * 40 in text and "SEXTA_PORT=8765" in text
    assert "ANTHROPIC_API_KEY=\n" in (tmp_path / ".env.example").read_text(encoding="utf-8")  # exemplo intacto


def test_cli_key_command_validates_and_saves(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["chave"]) == 1  # fora da pasta do projeto
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "não é uma chave")
    assert main(["chave"]) == 1 and not (tmp_path / ".env").exists()
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": f"  {FAKE_KEY}  ")
    monkeypatch.setattr(winsys, "instance_running", lambda *a, **k: False)
    assert main(["chave"]) == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8").strip() == f"ANTHROPIC_API_KEY={FAKE_KEY}"
    assert FAKE_KEY not in capsys.readouterr().out  # a chave nunca é exibida


def test_cli_status_shows_server_state_and_log_tail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SEXTA_DATA_DIR", str(tmp_path / "dados"))
    monkeypatch.setenv("SEXTA_PORT", "1")
    logs = tmp_path / "dados" / "logs"
    logs.mkdir(parents=True)
    (logs / "sexta.log").write_text("\n".join(f"linha {i}" for i in range(100)), encoding="utf-8")
    (logs / "falhas.log").write_text("Fatal Python error: Segmentation fault\n", encoding="utf-8")
    assert main(["status", "--linhas", "5"]) == 1
    out = capsys.readouterr().out
    assert "NÃO está rodando" in out and "sexta open" in out
    assert "linha 99" in out and "linha 94" not in out
    assert "Segmentation fault" in out


def test_log_stream_turns_prints_into_log_lines():
    import logging

    from sexta.__main__ import _LogStream

    records = []

    class Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("teste-saida")
    logger.addHandler(Collect())
    logger.setLevel(logging.INFO)
    stream = _LogStream(logger, logging.INFO)
    stream.write("baixando 10%\rbaixando 100%\nfim")
    stream.flush()
    assert records == ["baixando 10%", "baixando 100%", "fim"]
    assert stream.isatty() is False
