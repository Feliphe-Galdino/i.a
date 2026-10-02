"""Provedor Anthropic (Claude) — streaming, ferramentas, cache e fallback.

Pontos importantes da integração (API de 2026):

* **Raciocínio adaptativo**: Opus 5.5 e Sonnet 5.5 sempre "pensam"; o controle é o
  ``effort`` (low/medium/high/xhigh). Pedimos ``display: "summarized"`` para mostrar
  um resumo do raciocínio na interface. Haiku 4.5 não usa ``effort`` nem thinking.
* **Histórico só cresce (append-only)**: blocos de raciocínio ficam presos à conversa
  que os gerou. Por isso o *system prompt* é congelado por conversa e as memórias
  entram na mensagem do usuário. Se algo mudar mesmo assim (ex.: o usuário liga a
  busca na web no meio da conversa), ``prefix_mismatch_behavior: "drop_block"`` faz a
  API descartar os blocos inválidos em vez de falhar.
* **Fallback de recusa**: ``fallbacks: "default"`` faz a própria API reexecutar em
  outro modelo quando um classificador de segurança recusa por engano.
* **Cache de prompt**: marcador no system prompt + cache automático do histórico.
* **Recuperação**: se a conta/plataforma rejeitar um recurso opcional (beta), ele é
  desligado e a requisição é refeita — o assistente degrada em vez de parar.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from .base import (
    Completion,
    LLMError,
    LLMEvent,
    LLMRequest,
    StreamReset,
    TextDelta,
    ThinkingDelta,
    ToolUseStarted,
    Usage,
)
from .catalog import get_model

log = logging.getLogger(__name__)

BETA_FALLBACK = "server-side-fallback-2026-07-01"
BETA_THINKING_BINDING = "thinking-binding-controls-2026-08-01"
WEB_SEARCH_MAX_USES = 5


def strip_thinking_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove blocos de raciocínio do histórico (recuperação de último recurso)."""
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") == "assistant" and isinstance(content, list):
            kept = [b for b in content if b.get("type") not in ("thinking", "redacted_thinking")]
            cleaned.append({**msg, "content": kept or [{"type": "text", "text": "…"}]})
        else:
            cleaned.append(msg)
    return cleaned


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        *,
        refusal_fallback: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
    ):
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)
        self._fallback_enabled = refusal_fallback
        self._binding_enabled = True
        self._eager_enabled = True

    # ------------------------------------------------------------------
    def build_params(self, req: LLMRequest, *, strip_thinking: bool = False) -> dict[str, Any]:
        spec = get_model(req.model)

        tools: list[dict[str, Any]] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in req.tools
        ]
        if self._eager_enabled:
            # Entradas grandes (ex.: conteúdo de arquivo) chegam em streaming;
            # o executor valida cada entrada antes de rodar a ferramenta.
            for tool in tools:
                tool["eager_input_streaming"] = True
        if req.web_search and spec.web_search_tool:
            tools.append({"type": spec.web_search_tool, "name": "web_search", "max_uses": WEB_SEARCH_MAX_USES})

        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens or spec.max_output_tokens,
            "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            "messages": strip_thinking_blocks(req.messages) if strip_thinking else req.messages,
            # Cache automático do último bloco: turnos seguintes reaproveitam o histórico.
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            params["tools"] = tools

        betas: list[str] = []
        if spec.adaptive_thinking:
            thinking: dict[str, Any] = {"type": "adaptive", "display": "summarized"}
            if self._binding_enabled:
                thinking["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
                betas.append(BETA_THINKING_BINDING)
            params["thinking"] = thinking
        if spec.supports_effort and req.effort:
            params["output_config"] = {"effort": req.effort}
        if spec.supports_fallbacks and self._fallback_enabled:
            params["fallbacks"] = "default"
            betas.append(BETA_FALLBACK)
        if betas:
            params["betas"] = betas
        return params

    # ------------------------------------------------------------------
    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        strip_thinking = False
        json_retries = 0
        attempts = 0
        while True:
            attempts += 1
            if attempts > 6:
                raise LLMError("Não foi possível concluir a requisição após várias tentativas.")
            params = self.build_params(request, strip_thinking=strip_thinking)
            emitted = False
            try:
                async with self._client.beta.messages.stream(**params) as stream:
                    async for event in stream:
                        converted = _convert_event(event)
                        if converted is not None:
                            emitted = True
                            yield converted
                    final = await stream.get_final_message()
            except anthropic.BadRequestError as exc:
                message = _error_text(exc)
                lowered = message.lower()
                if not emitted:
                    if "fallback" in lowered and self._fallback_enabled:
                        log.warning("Fallback de recusa indisponível; desativando: %s", message)
                        self._fallback_enabled = False
                        continue
                    if ("block_binding" in lowered or "thinking-binding" in lowered) and self._binding_enabled:
                        log.warning("Controle de binding indisponível; desativando: %s", message)
                        self._binding_enabled = False
                        continue
                    if "eager_input_streaming" in lowered and self._eager_enabled:
                        log.warning("Streaming antecipado de ferramentas indisponível; desativando.")
                        self._eager_enabled = False
                        continue
                    if "signature" in lowered and "thinking" in lowered and not strip_thinking:
                        log.warning("Histórico de raciocínio inválido; reenviando sem ele.")
                        strip_thinking = True
                        continue
                if "credit balance" in lowered:
                    raise LLMError(
                        "Sua conta da Anthropic está sem créditos. Adicione créditos em "
                        "console.anthropic.com → Plans & Billing e tente de novo."
                    ) from exc
                raise LLMError(f"A API recusou a requisição: {message}") from exc
            except anthropic.AuthenticationError as exc:
                raise LLMError("Chave de API inválida. Verifique ANTHROPIC_API_KEY no arquivo .env.") from exc
            except anthropic.PermissionDeniedError as exc:
                raise LLMError(f"Sem permissão para usar este recurso/modelo: {_error_text(exc)}") from exc
            except anthropic.NotFoundError as exc:
                raise LLMError(f"Modelo ou recurso não encontrado ({request.model}).") from exc
            except anthropic.RateLimitError as exc:
                raise LLMError(
                    "Limite de uso da API atingido. Aguarde um pouco e tente de novo.", retryable=True
                ) from exc
            except anthropic.APIStatusError as exc:
                raise LLMError(
                    f"Erro do servidor da API ({exc.status_code}). Tente novamente.", retryable=exc.status_code >= 500
                ) from exc
            except anthropic.APIConnectionError as exc:
                raise LLMError("Sem conexão com a API. Verifique sua internet.", retryable=True) from exc
            except ValueError as exc:
                # JSON de entrada de ferramenta impossível de interpretar (streaming
                # antecipado). Não há tool_use completo para responder: refazemos o turno.
                json_retries += 1
                if json_retries > 2:
                    raise LLMError("O modelo gerou uma chamada de ferramenta inválida.") from exc
                yield StreamReset("entrada de ferramenta inválida; refazendo a resposta")
                continue

            transformations = getattr(final, "input_transformations", None)
            if transformations:
                log.info("input_transformations: %s", transformations)
            yield _completion(final)
            return


def _convert_event(event: Any) -> LLMEvent | None:
    etype = getattr(event, "type", None)
    if etype == "content_block_start":
        block = event.content_block
        if block.type == "tool_use":
            return ToolUseStarted(id=block.id, name=block.name, server=False)
        if block.type in ("server_tool_use", "mcp_tool_use"):
            return ToolUseStarted(id=block.id, name=block.name, server=True)
    elif etype == "content_block_delta":
        delta = event.delta
        if delta.type == "text_delta":
            return TextDelta(delta.text)
        if delta.type == "thinking_delta" and delta.thinking:
            return ThinkingDelta(delta.thinking)
    return None


def _completion(final: Any) -> Completion:
    usage = final.usage
    server_use = getattr(usage, "server_tool_use", None)
    stop_details = getattr(final, "stop_details", None)
    return Completion(
        content=[block.to_dict(mode="json") for block in final.content],
        stop_reason=final.stop_reason,
        model=final.model,
        usage=Usage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            web_searches=(server_use.web_search_requests or 0) if server_use else 0,
        ),
        stop_details=stop_details.to_dict(mode="json") if stop_details else None,
    )


def _error_text(exc: anthropic.APIStatusError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(getattr(exc, "message", exc))
