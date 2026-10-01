"""Catálogo de modelos: capacidades, preços e camada (tier) de cada modelo.

O roteador escolhe uma *camada* (rápido / equilibrado / profundo) e o catálogo diz
qual modelo atende essa camada e o que ele suporta. Para adicionar um modelo novo
(inclusive de outro provedor no futuro), basta registrar um ``ModelSpec`` aqui.

Preços em US$ por milhão de tokens (tabela de 2026-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Tier(StrEnum):
    FAST = "rapido"
    BALANCED = "equilibrado"
    DEEP = "profundo"

    @property
    def rank(self) -> int:
        return _TIER_ORDER.index(self)

    def shift(self, steps: int) -> Tier:
        idx = max(0, min(len(_TIER_ORDER) - 1, self.rank + steps))
        return _TIER_ORDER[idx]

    @property
    def label(self) -> str:
        return {"rapido": "Rápido", "equilibrado": "Equilibrado", "profundo": "Profundo"}[self.value]


_TIER_ORDER = [Tier.FAST, Tier.BALANCED, Tier.DEEP]

EFFORT_LEVELS = ["low", "medium", "high", "xhigh"]


def shift_effort(effort: str | None, steps: int) -> str | None:
    if effort is None:
        return None
    idx = EFFORT_LEVELS.index(effort) if effort in EFFORT_LEVELS else 1
    return EFFORT_LEVELS[max(0, min(len(EFFORT_LEVELS) - 1, idx + steps))]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    provider: str
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float
    context_tokens: int
    max_output_tokens: int
    supports_effort: bool
    adaptive_thinking: bool
    web_search_tool: str | None
    supports_fallbacks: bool

    def cost(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        web_searches: int = 0,
    ) -> float:
        total = (
            input_tokens * self.input_per_mtok
            + output_tokens * self.output_per_mtok
            + cache_read_tokens * self.cache_read_per_mtok
            + cache_write_tokens * self.cache_write_per_mtok
        ) / 1_000_000
        return total + web_searches * WEB_SEARCH_COST_USD


# Busca na web (ferramenta de servidor da Anthropic): US$ 10 por 1.000 buscas.
WEB_SEARCH_COST_USD = 0.01

MODELS: dict[str, ModelSpec] = {
    spec.id: spec
    for spec in [
        ModelSpec(
            id="claude-opus-5-5",
            label="Claude Opus 5.5",
            provider="anthropic",
            input_per_mtok=4.0,
            output_per_mtok=20.0,
            cache_read_per_mtok=0.20,
            cache_write_per_mtok=5.0,
            context_tokens=1_000_000,
            max_output_tokens=64_000,
            supports_effort=True,
            adaptive_thinking=True,
            web_search_tool="web_search_20260209",
            supports_fallbacks=True,
        ),
        ModelSpec(
            id="claude-sonnet-5-5",
            label="Claude Sonnet 5.5",
            provider="anthropic",
            input_per_mtok=2.0,
            output_per_mtok=10.0,
            cache_read_per_mtok=0.20,
            cache_write_per_mtok=2.50,
            context_tokens=1_000_000,
            max_output_tokens=32_000,
            supports_effort=True,
            adaptive_thinking=True,
            web_search_tool="web_search_20260209",
            supports_fallbacks=True,
        ),
        ModelSpec(
            id="claude-haiku-4-5",
            label="Claude Haiku 4.5",
            provider="anthropic",
            input_per_mtok=1.0,
            output_per_mtok=5.0,
            cache_read_per_mtok=0.10,
            cache_write_per_mtok=1.25,
            context_tokens=200_000,
            max_output_tokens=16_000,
            supports_effort=False,
            adaptive_thinking=False,
            web_search_tool="web_search_20250305",
            supports_fallbacks=False,
        ),
    ]
}

OFFLINE_MODEL = ModelSpec(
    id="offline",
    label="Modo offline",
    provider="offline",
    input_per_mtok=0,
    output_per_mtok=0,
    cache_read_per_mtok=0,
    cache_write_per_mtok=0,
    context_tokens=1_000_000,
    max_output_tokens=4_000,
    supports_effort=False,
    adaptive_thinking=False,
    web_search_tool=None,
    supports_fallbacks=False,
)


def get_model(model_id: str) -> ModelSpec:
    """Retorna a especificação do modelo; modelos desconhecidos recebem um perfil
    conservador (sem effort/thinking) para não gerar requisições inválidas."""
    if model_id in MODELS:
        return MODELS[model_id]
    if model_id == OFFLINE_MODEL.id:
        return OFFLINE_MODEL
    return ModelSpec(
        id=model_id,
        label=model_id,
        provider="anthropic",
        input_per_mtok=4.0,
        output_per_mtok=20.0,
        cache_read_per_mtok=0.4,
        cache_write_per_mtok=5.0,
        context_tokens=200_000,
        max_output_tokens=16_000,
        supports_effort=False,
        adaptive_thinking=False,
        web_search_tool=None,
        supports_fallbacks=False,
    )
