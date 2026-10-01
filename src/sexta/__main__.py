"""Linha de comando da Sexta-Feira.

sexta serve      inicia o servidor e abre a interface no navegador
sexta token      mostra o token de acesso
sexta doctor     verifica a instalação e a configuração
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import threading
import webbrowser

from . import __version__
from .config import Settings

BANNER = r"""
   _____           __                 ______     _
  / ___/___  _  __/ /_____ _         / ____/__  (_)________ _
  \__ \/ _ \| |/_/ __/ __ `/ ______ / /_  / _ \/ / ___/ __ `/
 ___/ /  __/>  </ /_/ /_/ / /_____// __/ /  __/ / /  / /_/ /
/____/\___/_/|_|\__/\__,_/        /_/    \___/_/_/   \__,_/
"""


def _url(settings: Settings, with_token: bool = True) -> str:
    host = "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host
    base = f"http://{host}:{settings.port}/"
    return f"{base}?token={settings.token}" if with_token else base


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    settings = Settings()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

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

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(_url(settings))).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")
    return 0


def cmd_token(_args: argparse.Namespace) -> int:
    settings = Settings()
    print(settings.token)
    print(f"\nLink direto: {_url(settings)}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    settings = Settings()
    ok = True

    def check(label: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'OK' if passed else '!!'}] {label}" + (f"\n       → {hint}" if hint and not passed else ""))

    print(f"Sexta-Feira v{__version__} — diagnóstico\n")
    check(
        f"Python {sys.version.split()[0]} (>= 3.11)", sys.version_info >= (3, 11), "Instale Python 3.11 ou mais novo."
    )
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
    print("\nTudo certo!" if ok else "\nHá itens para revisar acima.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sexta", description="Sexta-Feira — assistente pessoal de IA")
    parser.add_argument("--version", action="version", version=f"sexta-feira {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="inicia o servidor e a interface")
    serve.add_argument("--host", help="endereço (padrão: SEXTA_HOST ou 127.0.0.1)")
    serve.add_argument("--port", type=int, help="porta (padrão: SEXTA_PORT ou 8765)")
    serve.add_argument("--no-browser", action="store_true", help="não abrir o navegador")
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("token", help="mostra o token de acesso").set_defaults(func=cmd_token)
    sub.add_parser("doctor", help="verifica a instalação").set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["serve", *(argv or [])])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
