"""Contrato comum entre a Sexta-Feira e qualquer provedor de IA.

O orquestrador conversa apenas com esta interface. Assim, trocar ou adicionar
provedores (Anthropic, modelos locais, outros serviços) não exige mexer no núcleo.

Formato canônico das mensagens: o formato de *content blocks* da Messages API
(``{"role": "user", "content": [{"type": "text", "text": "..."}]}``). É expressivo
(texto, raciocínio, chamadas de ferramenta, resultados) e bem documentado; um
provedor que use outro formato traduz na borda.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class LLMRequest:
    model: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[ToolSpec] = field(default_factory=list)
    effort: str | None = None
    web_search: bool = False
    max_tokens: int | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.web_searches += other.web_searches


# --- Eventos emitidos durante o streaming -----------------------------------


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolUseStarted:
    id: str
    name: str
    server: bool = False


@dataclass
class StreamReset:
    """O provedor descartou a saída parcial e vai tentar de novo."""

    reason: str


@dataclass
class Completion:
    content: list[dict[str, Any]]
    stop_reason: str | None
    model: str
    usage: Usage
    stop_details: dict[str, Any] | None = None


LLMEvent = TextDelta | ThinkingDelta | ToolUseStarted | StreamReset | Completion


class LLMError(Exception):
    """Erro de provedor com mensagem amigável para o usuário."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        """Gera eventos; o último é sempre um ``Completion``."""
        ...
