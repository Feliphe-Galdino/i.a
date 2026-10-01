"""Camada de provedores de IA (LLMs)."""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider


def build_provider(settings: Settings) -> LLMProvider:
    """Escolhe o provedor disponível: Anthropic se houver chave, senão offline."""
    if settings.api_key:
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.api_key, refusal_fallback=settings.refusal_fallback)
    from .offline import OfflineProvider

    return OfflineProvider()
