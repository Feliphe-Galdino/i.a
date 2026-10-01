"""Configuração estática da Sexta-Feira.

Duas camadas de configuração convivem no sistema:

1. ``Settings`` (este arquivo): vem do ambiente / arquivo ``.env``. Contém segredos
   (chave de API) e parâmetros de infraestrutura. Só muda reiniciando o servidor.
2. ``RuntimeSettings`` (``core/runtime_settings.py``): preferências editáveis pela
   interface (nível de autonomia, permissões, orçamento...). Ficam no banco.

Segredos NUNCA vão para o banco nem para a IA — apenas para o cliente da API.
"""

from __future__ import annotations

import contextlib
import secrets
from functools import cached_property
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SEXTA_",
        extra="ignore",
    )

    # --- Provedores de IA -------------------------------------------------
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "SEXTA_ANTHROPIC_API_KEY"),
    )
    refusal_fallback: bool = True

    model_fast: str = "claude-haiku-4-5"
    model_balanced: str = "claude-sonnet-5-5"
    model_deep: str = "claude-opus-5-5"

    # --- Servidor ----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8765
    # Hosts extras aceitos no cabeçalho Host (proteção contra DNS rebinding).
    allowed_hosts: str = ""
    access_token: SecretStr | None = None

    # --- Armazenamento ----------------------------------------------------
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".sexta-feira")
    workspace_dir: Path = Field(default_factory=lambda: Path.home() / "SextaFeira")
    fs_extra_roots: str = ""

    # --- Comportamento ------------------------------------------------------
    daily_budget_usd: float = 5.0
    timezone: str | None = None
    max_tool_rounds: int = 15
    tool_timeout_s: float = 60.0
    approval_timeout_s: float = 300.0
    max_tool_output_chars: int = 20_000

    # ------------------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "sexta.db"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "lixeira"

    @property
    def extra_roots(self) -> list[Path]:
        parts = [p.strip() for p in self.fs_extra_roots.replace("\n", ";").split(";")]
        return [Path(p).expanduser() for p in parts if p]

    @property
    def host_allowlist(self) -> list[str]:
        hosts = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
        hosts.update(h.strip() for h in self.allowed_hosts.split(",") if h.strip())
        if self.host not in ("0.0.0.0", "::"):
            hosts.add(self.host)
        return sorted(hosts)

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.workspace_dir, self.trash_dir):
            d.mkdir(parents=True, exist_ok=True)

    @cached_property
    def token(self) -> str:
        """Token de acesso à API local (gerado e salvo na primeira execução)."""
        if self.access_token is not None:
            return self.access_token.get_secret_value()
        token_file = self.data_dir / "token"
        if token_file.exists():
            value = token_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        self.data_dir.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(32)
        token_file.write_text(value, encoding="utf-8")
        with contextlib.suppress(OSError):  # Windows ignora permissões POSIX
            token_file.chmod(0o600)
        return value

    @property
    def api_key(self) -> str | None:
        return self.anthropic_api_key.get_secret_value() if self.anthropic_api_key else None
