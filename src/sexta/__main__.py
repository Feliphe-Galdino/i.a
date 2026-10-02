"""Linha de comando da Sexta-Feira.

sexta serve              inicia o servidor e abre a interface no navegador
sexta open               abre a janela da assistente (sobe o servidor se preciso)
sexta stop               encerra o servidor que roda em segundo plano
sexta autostart on|off   liga/desliga "iniciar com o Windows" (--janela abre a interface também)
sexta autostart status   mostra se está ligado
sexta voz instalar       baixa os modelos de voz (ativação + transcrição)
sexta voz dispositivos   lista os microfones
sexta voz testar         grava 5 s, transcreve e repete em voz alta
sexta memoria instalar   baixa o modelo de busca por significado e indexa as memórias
sexta token              mostra o token de acesso
sexta doctor             verifica a instalação e a configuração
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import threading
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__, winsys
from .config import Settings

BANNER = r"""
   _____           __                 ______     _
  / ___/___  _  __/ /_____ _         / ____/__  (_)________ _
  \__ \/ _ \| |/_/ __/ __ `/ ______ / /_  / _ \/ / ___/ __ `/
 ___/ /  __/>  </ /_/ /_/ / /_____// __/ /  __/ / /  / /_/ /
/____/\___/_/|_|\__/\__,_/        /_/    \___/_/_/   \__,_/
"""


def _url(settings: Settings, *, with_token: bool = True, voice: bool = False) -> str:
    host = "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host
    base = f"http://{host}:{settings.port}/"
    if not with_token:
        return base
    return f"{base}?token={settings.token}" + ("&voz=1#/chat" if voice else "")


def _setup_logging(settings: Settings, headless: bool) -> bool:
    """Sem console (pythonw/inicialização automática), os logs vão para um arquivo."""
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    if headless or sys.stdout is None:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            settings.logs_dir / "sexta.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        logging.basicConfig(level=logging.INFO, format=fmt, handlers=[handler], force=True)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # a UI consulta o status a cada 5 s
        return True
    logging.basicConfig(level=logging.INFO, format=fmt)
    return False


def _open_window(settings: Settings, *, app_window: bool) -> None:
    if app_window:
        used = winsys.open_app_window(
            _url(settings, voice=True), profile_dir=settings.browser_profile_dir, browser_override=settings.browser
        )
        logging.getLogger("sexta").info("Janela da assistente aberta (%s)", used)
    else:
        webbrowser.open(_url(settings))


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    settings = Settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    headless = _setup_logging(settings, args.headless)
    log = logging.getLogger("sexta")

    if winsys.instance_running(settings.port):
        # Já existe uma Sexta-Feira rodando: só abre a janela.
        log.info("Servidor já em execução na porta %s", settings.port)
        print(f"A Sexta-Feira já está rodando em {_url(settings, with_token=False)}")
        if not args.no_browser:
            _open_window(settings, app_window=args.app_window)
        return 0

    app = create_app(settings)
    sexta = app.state.sexta
    print(BANNER)
    print(f"  Sexta-Feira v{__version__}  ·  provedor: {sexta.provider.name}")
    if sexta.provider.name == "offline":
        print("  ⚠ Sem ANTHROPIC_API_KEY: rodando em modo offline (veja o README).")
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  ⚠ Servidor exposto em {settings.host}. Garanta firewall e mantenha o token em segredo.")
    print(f"\n  Interface: {_url(settings)}")
    print("  (o link contém seu token de acesso — não compartilhe)\n")
    log.info("Sexta-Feira v%s iniciando (provedor: %s, porta: %s)", __version__, sexta.provider.name, settings.port)

    if not args.no_browser:
        threading.Timer(1.2, lambda: _open_window(settings, app_window=args.app_window)).start()

    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info" if headless else "warning",
        log_config=None if headless else uvicorn.config.LOGGING_CONFIG,
    )
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()
    return 0


def cmd_open(_args: argparse.Namespace) -> int:
    settings = Settings()
    if winsys.instance_running(settings.port):
        _open_window(settings, app_window=True)
        print("Janela da Sexta-Feira aberta.")
    else:
        winsys.spawn_background_server(Path.cwd())
        print("Iniciando a Sexta-Feira em segundo plano… a janela abrirá em instantes.")
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    settings = Settings()
    if not winsys.instance_running(settings.port):
        print("A Sexta-Feira não está rodando.")
        return 0
    request = urllib.request.Request(
        f"http://127.0.0.1:{settings.port}/api/system/shutdown",
        method="POST",
        headers={"Authorization": f"Bearer {settings.token}"},
    )
    with urllib.request.urlopen(request, timeout=5) as resp:  # noqa: S310
        json.loads(resp.read().decode())
    print("Sexta-Feira encerrada.")
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    manager = winsys.AutostartManager(Path.cwd())
    if not manager.supported:
        print("Iniciar com o sistema está disponível apenas no Windows.")
        return 1
    if args.action == "on":
        status = manager.enable(window=args.janela)
        extra = " e abrir a interface" if args.janela else " (voz local, sem janela)"
        print(f"✔ A Sexta-Feira vai iniciar junto com o Windows{extra}.")
    elif args.action == "off":
        status = manager.disable()
        print("✔ Início automático desligado.")
    else:
        status = manager.status()
        print(f"Início automático: {'LIGADO' if status['enabled'] else 'desligado'}")
        if status["enabled"] and not status["up_to_date"]:
            print("  ⚠ O comando registrado está desatualizado. Rode `sexta autostart on` de novo nesta pasta.")
    print(f"Comando: {status['command']}")
    return 0


def _runtime(settings: Settings):
    from .core.runtime_settings import RuntimeSettingsStore
    from .memory.db import Database

    db = Database(settings.db_path)
    try:
        return RuntimeSettingsStore(db, settings).get()
    finally:
        db.close()


def cmd_voice(args: argparse.Namespace) -> int:
    from .voice.audio import VoiceDependencyError, list_input_devices
    from .voice.models import ModelStore

    settings = Settings()
    settings.ensure_dirs()
    runtime = _runtime(settings)
    size = args.modelo or runtime.voice_whisper_model
    store = ModelStore(settings.models_dir)

    if args.acao == "dispositivos":
        try:
            devices = list_input_devices()
        except VoiceDependencyError as exc:
            print(exc)
            return 1
        for dev in devices:
            mark = " (padrão)" if dev["default"] else ""
            print(f"  [{dev['index']}] {dev['name']} — {dev['hostapi']}{mark}")
        print("\nPara escolher, use Configurações → Voz → Microfone (ou deixe o padrão do Windows).")
        return 0

    if args.acao == "instalar":

        def progress(what: str, fraction: float) -> None:
            print(f"\r  {what}: {fraction * 100:5.1f}%", end="", flush=True)

        try:
            print("Baixando o modelo de ativação (Vosk pt, ~31 MB)…")
            store.download_vosk(progress)
            print(f"\nBaixando o modelo de transcrição Whisper '{size}' (pode levar alguns minutos)…")
            store.download_whisper(size, progress)
        except Exception as exc:  # noqa: BLE001
            print(f"\nFalha no download: {exc}")
            return 1
        print(f"\n✔ Modelos prontos em {store.base}")
        return 0

    # testar: grava, transcreve e repete
    try:
        import sounddevice as sd  # type: ignore[import-not-found]

        from .voice.audio import Tones
        from .voice.dsp import rms
        from .voice.recognition import WhisperTranscriber
        from .voice.tts import build_speaker
    except (ImportError, OSError) as exc:
        print(f'Recursos de voz não instalados: {exc}\nRode: pip install -e ".[voz]"')
        return 1
    if not store.whisper_ready(size):
        print("Modelo de transcrição ausente. Rode primeiro: sexta voz instalar")
        return 1
    print("🎙 Fale algo depois do bipe (5 segundos)…")
    Tones().play("on")
    recording = sd.rec(5 * 16_000, samplerate=16_000, channels=1, dtype="float32")
    sd.wait()
    audio = recording[:, 0]
    print(f"Nível médio do microfone: {rms(audio):.4f} (silêncio ≈ 0,001–0,005; fala ≈ 0,02–0,2)")
    print("Transcrevendo…")
    text = WhisperTranscriber(store.whisper_dir(size)).transcribe(audio)
    print(f"Você disse: {text or '(nada reconhecido)'}")
    speaker = build_speaker(voice=runtime.voice_tts_voice, rate=runtime.voice_tts_rate)
    done = threading.Event()
    speaker.say(f"Você disse: {text}" if text else "Não entendi. Tente falar mais perto do microfone.", done.set)
    done.wait(30)
    speaker.close()
    return 0


def cmd_memory(_args: argparse.Namespace) -> int:
    """Baixa/carrega o modelo de embeddings e indexa todas as memórias."""
    from .memory.db import Database
    from .memory.semantic import FastEmbedEmbedder, SemanticIndex, SemanticUnavailable
    from .voice.models import ModelStore

    settings = Settings()
    settings.ensure_dirs()
    store = ModelStore(settings.models_dir)
    print("Preparando a busca por significado (download de ~220 MB na primeira vez)…")
    try:
        embedder = FastEmbedEmbedder(store.embeddings_dir)
    except SemanticUnavailable as exc:
        print(exc)
        return 1
    db = Database(settings.db_path)
    try:
        index = SemanticIndex(db, lambda: embedder)
        index.embedder, index.state = embedder, "ready"
        count = index.backfill()
        status = index.status()
    finally:
        db.close()
    print(f"Pronto: {count} memória(s) indexada(s) agora; {status['indexed']} de {status['total']} no total.")
    return 0


def cmd_token(_args: argparse.Namespace) -> int:
    settings = Settings()
    print(settings.token)
    print(f"\nLink direto: {_url(settings)}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    settings = Settings()
    ok = True

    def check(label: str, passed: bool, hint: str = "", *, required: bool = True) -> None:
        nonlocal ok
        if required:
            ok = ok and passed
        mark = "OK" if passed else ("!!" if required else "--")
        print(f"  [{mark}] {label}" + (f"\n       → {hint}" if hint and not passed else ""))

    print(f"Sexta-Feira v{__version__} — diagnóstico\n")
    check(
        f"Python {sys.version.split()[0]} (>= 3.11)", sys.version_info >= (3, 11), "Instale Python 3.11 ou mais novo."
    )
    check("Windows", winsys.is_windows(), "A Sexta-Feira foi feita para o Windows 11.", required=False)
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        fts = True
    except sqlite3.Error:
        fts = False
    check(f"SQLite {sqlite3.sqlite_version} com FTS5", fts, "Atualize o Python (o SQLite embutido não tem FTS5).")
    check(
        "Chave da Anthropic configurada",
        bool(settings.api_key),
        "Preencha ANTHROPIC_API_KEY no arquivo .env (modo offline até lá).",
    )
    try:
        settings.ensure_dirs()
        writable = True
    except OSError:
        writable = False
    check(f"Pasta de dados: {settings.data_dir}", writable, "Verifique permissões ou defina SEXTA_DATA_DIR.")
    check(
        f"Pasta de trabalho: {settings.workspace_dir}", settings.workspace_dir.exists(), "Defina SEXTA_WORKSPACE_DIR."
    )
    for root in settings.extra_roots:
        check(f"Pasta extra liberada: {root}", root.exists(), "A pasta não existe.")
    check(
        f"Servidor restrito ao computador local ({settings.host})",
        settings.host in ("127.0.0.1", "localhost", "::1"),
        "Use SEXTA_HOST=127.0.0.1 a menos que saiba o que está fazendo.",
    )
    if winsys.is_windows():
        browser = winsys.find_browser(settings.browser)
        check(
            f"Navegador para a voz: {browser or 'não encontrado'}",
            browser is not None,
            "Instale o Google Chrome (recomendado para reconhecimento de voz) ou defina SEXTA_BROWSER.",
        )
        status = winsys.AutostartManager(Path.cwd()).status()
        check(
            "Iniciar com o Windows",
            bool(status["enabled"]),
            "Rode `sexta autostart on` nesta pasta para ligar.",
            required=False,
        )
    try:
        import fastembed  # noqa: F401

        semantic = True
    except ImportError:
        semantic = False
    check(
        "Busca por significado (fastembed)",
        semantic,
        'Opcional: pip install -e ".[memoria]" e depois sexta memoria instalar',
        required=False,
    )
    print("\nTudo certo!" if ok else "\nHá itens para revisar acima.")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sexta", description="Sexta-Feira — assistente pessoal de IA")
    parser.add_argument("--version", action="version", version=f"sexta-feira {__version__}")
    parser.add_argument("--workdir", help="pasta do projeto (onde está o .env)")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="inicia o servidor e a interface")
    serve.add_argument("--host", help="endereço (padrão: SEXTA_HOST ou 127.0.0.1)")
    serve.add_argument("--port", type=int, help="porta (padrão: SEXTA_PORT ou 8765)")
    serve.add_argument("--no-browser", action="store_true", help="não abrir o navegador")
    serve.add_argument("--app-window", action="store_true", help="abrir a janela dedicada (Chrome/Edge) com voz")
    serve.add_argument("--headless", action="store_true", help="sem console: grava logs em arquivo")
    serve.add_argument("--workdir", default=argparse.SUPPRESS, help="pasta do projeto (onde está o .env)")
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("open", help="abre a janela da assistente").set_defaults(func=cmd_open)
    sub.add_parser("stop", help="encerra o servidor em segundo plano").set_defaults(func=cmd_stop)
    auto = sub.add_parser("autostart", help="iniciar com o Windows")
    auto.add_argument("action", choices=["on", "off", "status"])
    auto.add_argument("--janela", action="store_true", help="abrir também a janela da interface ao ligar")
    auto.set_defaults(func=cmd_autostart)
    voz = sub.add_parser("voz", help="voz local (microfone do PC)")
    voz.add_argument("acao", choices=["instalar", "dispositivos", "testar"])
    voz.add_argument("--modelo", choices=["base", "small", "medium", "large-v3-turbo"], help="modelo de transcrição")
    voz.set_defaults(func=cmd_voice)
    mem = sub.add_parser("memoria", help="memória semântica (busca por significado)")
    mem.add_argument("acao", choices=["instalar"])
    mem.set_defaults(func=cmd_memory)
    sub.add_parser("token", help="mostra o token de acesso").set_defaults(func=cmd_token)
    sub.add_parser("doctor", help="verifica a instalação").set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["serve", *(argv or [])])
    if getattr(args, "workdir", None):
        os.chdir(args.workdir)  # o .env é lido da pasta atual
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
