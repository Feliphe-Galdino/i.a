"""Preferências editáveis pela interface (persistidas no banco).

Diferente de ``Settings`` (arquivo .env), estas opções mudam em tempo real, sem
reiniciar: nível de autonomia, permissões por capacidade, prioridade de roteamento,
orçamento, modelos por camada etc.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..config import Settings
from ..memory.db import Database
from ..security.permissions import CAPABILITIES, DEFAULT_AUTONOMY

PermissionValue = Literal["allow", "ask", "deny"]
RoutingPriority = Literal["qualidade", "equilibrio", "economia"]


class RuntimeSettings(BaseModel):
    user_name: str = ""
    assistant_name: str = "Sexta-Feira"
    autonomy_level: int = Field(default=DEFAULT_AUTONOMY, ge=0, le=3)
    permission_overrides: dict[str, PermissionValue] = Field(default_factory=dict)
    routing_priority: RoutingPriority = "equilibrio"
    daily_budget_usd: float = Field(default=5.0, ge=0)
    budget_hard_stop: bool = False
    web_search: bool = True
    fs_roots: list[str] = Field(default_factory=list)
    tier_models: dict[str, str] = Field(default_factory=dict)
    custom_instructions: str = Field(default="", max_length=4000)

    # --- Voz local (no PC) ---------------------------------------------------
    voice_engine: Literal["local", "navegador", "desligado"] = "local"
    voice_mode: Literal["ambos", "voz"] = "ambos"
    voice_wake: bool = True
    voice_name_only: bool = False
    voice_claps: bool = True
    voice_clap_sensitivity: float = Field(default=0.5, ge=0, le=1)
    voice_input_device: str = ""
    voice_tts_voice: str = ""
    voice_tts_rate: int = Field(default=1, ge=-10, le=10)
    voice_whisper_model: Literal["base", "small", "medium", "large-v3-turbo"] = "small"
    voice_speak_alerts: bool = True

    # --- Informações: notícias, mercado, clima, resumos ---------------------------
    intel_enabled: bool = True
    semantic_memory: bool = True
    city: str = Field(default="", max_length=80)
    watchlist: list[str] = Field(default_factory=lambda: ["IBOV", "USD", "EUR", "BTC", "PETR4", "VALE3", "ITUB4"])
    news_topics: list[str] = Field(default_factory=lambda: ["brasil", "mundo", "economia", "tecnologia"])
    briefing_enabled: bool = True
    briefing_times: list[str] = Field(default_factory=lambda: ["08:00"])

    @field_validator("permission_overrides")
    @classmethod
    def _known_capabilities(cls, value: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in value.items() if k in CAPABILITIES}

    @field_validator("briefing_times")
    @classmethod
    def _valid_times(cls, value: list[str]) -> list[str]:
        out = []
        for item in value:
            item = item.strip()
            parts = item.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError(f"horário inválido: {item!r} (use HH:MM)")
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError(f"horário inválido: {item!r}")
            out.append(f"{hour:02d}:{minute:02d}")
        return sorted(set(out))[:6]

    @field_validator("watchlist", "news_topics")
    @classmethod
    def _short_lists(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip() for v in value if v and v.strip()]
        return list(dict.fromkeys(cleaned))[:25]

    @field_validator("tier_models")
    @classmethod
    def _known_tiers(cls, value: dict[str, str]) -> dict[str, str]:
        return {k: v.strip() for k, v in value.items() if k in ("rapido", "equilibrado", "profundo") and v.strip()}


class RuntimeSettingsStore:
    KEY = "runtime"

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self._defaults = RuntimeSettings(daily_budget_usd=settings.daily_budget_usd)
        self._cache: RuntimeSettings | None = None

    def get(self) -> RuntimeSettings:
        if self._cache is None:
            row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (self.KEY,))
            if row:
                merged = {**self._defaults.model_dump(), **json.loads(row["value"])}
                self._cache = RuntimeSettings.model_validate(merged)
            else:
                self._cache = self._defaults.model_copy()
        return self._cache.model_copy(deep=True)

    def update(self, changes: dict) -> RuntimeSettings:
        merged = {**self.get().model_dump(), **changes}
        validated = RuntimeSettings.model_validate(merged)
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (self.KEY, validated.model_dump_json()),
        )
        self._cache = validated
        return validated.model_copy(deep=True)
