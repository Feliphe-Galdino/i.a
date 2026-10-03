"""Camada de provedores de IA (LLMs)."""

from __future__ import annotations

from ..config import Settings
from .base import LLMProvider


def build_provider(settings: Settings) -> LLMProvider:
    """Escolhe de onde vem a IA.

    ``auto`` (padrão) prefere a **assinatura** (Claude Code logado no seu plano Pro/Max, sem
    custo extra); sem o `claude` instalado, usa a chave da API (créditos); sem nada, offline.
    """
    mode = settings.llm_provider
    if mode in ("auto", "assinatura"):
        from .claude_code import ClaudeCodeProvider, find_claude

        executable = find_claude(settings.claude_path)
        if executable or mode == "assinatura":
            return ClaudeCodeProvider(settings.data_dir / "claude-code", executable=executable)
    if mode in ("auto", "api") and settings.api_key:
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.api_key, refusal_fallback=settings.refusal_fallback)
    from .offline import OfflineProvider

    return OfflineProvider()


PROVIDER_LABELS = {
    "claude-code": "Claude Pro (assinatura)",
    "anthropic": "API Anthropic (créditos)",
    "offline": "offline",
}
