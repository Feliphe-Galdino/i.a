"""Provedor Anthropic: formato das requisições e recuperação de erros (sem rede)."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from sexta.llm.anthropic_provider import (
    BETA_FALLBACK,
    BETA_THINKING_BINDING,
    AnthropicProvider,
    strip_thinking_blocks,
)
from sexta.llm.base import Completion, LLMError, LLMRequest, StreamReset, TextDelta, ThinkingDelta, ToolSpec

TOOLS = [ToolSpec("fs_read", "Lê arquivo", {"type": "object", "properties": {"path": {"type": "string"}}})]


def request(model: str, **kwargs) -> LLMRequest:
    return LLMRequest(
        model=model,
        system="Você é a Sexta-Feira.",
        messages=[{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
        tools=TOOLS,
        **kwargs,
    )


def test_opus_params():
    params = AnthropicProvider("k").build_params(request("claude-opus-5-5", effort="high", web_search=True))
    assert params["model"] == "claude-opus-5-5"
    assert params["max_tokens"] == 64_000
    assert params["thinking"] == {
        "type": "adaptive",
        "display": "summarized",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert params["output_config"] == {"effort": "high"}
    assert params["fallbacks"] == "default"
    assert set(params["betas"]) == {BETA_FALLBACK, BETA_THINKING_BINDING}
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["cache_control"] == {"type": "ephemeral"}
    custom, server = params["tools"]
    assert custom["eager_input_streaming"] is True and custom["name"] == "fs_read"
    assert server == {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
    assert "tool_choice" not in params  # escolha forçada de ferramenta não é suportada no Opus 5.5
    assert "temperature" not in params


def test_haiku_params_are_conservative():
    params = AnthropicProvider("k").build_params(request("claude-haiku-4-5", effort="medium", web_search=True))
    assert "thinking" not in params
    assert "output_config" not in params
    assert "fallbacks" not in params
    assert "betas" not in params
    assert params["tools"][-1]["type"] == "web_search_20250305"


def test_fallback_can_be_disabled():
    params = AnthropicProvider("k", refusal_fallback=False).build_params(request("claude-sonnet-5-5"))
    assert "fallbacks" not in params
    assert params["betas"] == [BETA_THINKING_BINDING]


def test_strip_thinking_blocks():
    history = [
        {"role": "user", "content": [{"type": "text", "text": "oi"}]},
        {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "x", "signature": "s"}, {"type": "text", "text": "olá"}],
        },
        {"role": "assistant", "content": [{"type": "redacted_thinking", "data": "z"}]},
    ]
    cleaned = strip_thinking_blocks(history)
    assert cleaned[1]["content"] == [{"type": "text", "text": "olá"}]
    assert cleaned[2]["content"] == [{"type": "text", "text": "…"}]
    assert history[1]["content"][0]["type"] == "thinking"  # original intacto


# --- Streaming com cliente falso ------------------------------------------


def final_message(**overrides) -> BetaMessage:
    data = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [
            {"type": "thinking", "thinking": "pensando", "signature": "sig"},
            {"type": "text", "text": "Olá!", "citations": None},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": 20,
            "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0},
        },
    }
    data.update(overrides)
    return BetaMessage.model_validate(data)


def delta(kind: str, **fields) -> SimpleNamespace:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type=kind, **fields))


class FakeStream:
    def __init__(self, events, final, error: Exception | None = None, iter_error: Exception | None = None):
        self.events, self.final, self.error, self.iter_error = events, final, error, iter_error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for event in self.events:
            yield event
        if self.iter_error:
            raise self.iter_error

    async def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, streams):
        self.calls: list[dict] = []
        self._streams = list(streams)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **params):
        self.calls.append(params)
        return self._streams.pop(0)


def bad_request(message: str) -> anthropic.BadRequestError:
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"), json=body)
    return anthropic.BadRequestError(message, response=response, body=body)


async def collect(provider, req):
    return [event async for event in provider.stream(req)]


async def test_stream_converts_events_and_usage():
    stream = FakeStream([delta("thinking_delta", thinking="hmm"), delta("text_delta", text="Olá!")], final_message())
    provider = AnthropicProvider("k", client=FakeClient([stream]))
    events = await collect(provider, request("claude-opus-5-5"))
    assert isinstance(events[0], ThinkingDelta) and isinstance(events[1], TextDelta)
    completion = events[-1]
    assert isinstance(completion, Completion)
    assert completion.content[0] == {"type": "thinking", "thinking": "pensando", "signature": "sig"}
    assert completion.usage.cache_read_tokens == 100
    assert completion.usage.cache_write_tokens == 20
    assert completion.usage.web_searches == 2


async def test_unsupported_fallback_is_disabled_and_retried():
    client = FakeClient(
        [
            FakeStream([], None, error=bad_request("fallbacks: Extra inputs are not permitted")),
            FakeStream([], final_message()),
        ]
    )
    provider = AnthropicProvider("k", client=client)
    events = await collect(provider, request("claude-opus-5-5"))
    assert isinstance(events[-1], Completion)
    assert "fallbacks" in client.calls[0] and "fallbacks" not in client.calls[1]
    # E continua desligado nas próximas requisições
    client._streams.append(FakeStream([], final_message()))
    await collect(provider, request("claude-opus-5-5"))
    assert "fallbacks" not in client.calls[2]


async def test_invalid_thinking_signature_strips_and_retries():
    error = bad_request("messages.1.content.0: Invalid `signature` in `thinking` block.")
    client = FakeClient([FakeStream([], None, error=error), FakeStream([], final_message())])
    provider = AnthropicProvider("k", client=client)
    req = request("claude-opus-5-5")
    req.messages = [
        {"role": "user", "content": [{"type": "text", "text": "oi"}]},
        {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "x", "signature": "s"}, {"type": "text", "text": "olá"}],
        },
        {"role": "user", "content": [{"type": "text", "text": "e aí?"}]},
    ]
    await collect(provider, req)
    assert client.calls[1]["messages"][1]["content"] == [{"type": "text", "text": "olá"}]


async def test_other_bad_request_becomes_friendly_error():
    client = FakeClient([FakeStream([], None, error=bad_request("max_tokens: too large"))])
    with pytest.raises(LLMError, match="max_tokens"):
        await collect(AnthropicProvider("k", client=client), request("claude-opus-5-5"))


async def test_unparseable_tool_json_resets_stream():
    client = FakeClient(
        [
            FakeStream([delta("text_delta", text="parcial")], None, iter_error=ValueError("bad json")),
            FakeStream([delta("text_delta", text="ok")], final_message()),
        ]
    )
    events = await collect(AnthropicProvider("k", client=client), request("claude-opus-5-5"))
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["TextDelta", "StreamReset", "TextDelta", "Completion"]
    assert isinstance(events[1], StreamReset)


async def test_unsupported_eager_streaming_is_disabled_and_retried():
    error = bad_request("tools.0.eager_input_streaming: Extra inputs are not permitted")
    client = FakeClient([FakeStream([], None, error=error), FakeStream([], final_message())])
    await collect(AnthropicProvider("k", client=client), request("claude-haiku-4-5"))
    assert client.calls[0]["tools"][0]["eager_input_streaming"] is True
    assert "eager_input_streaming" not in client.calls[1]["tools"][0]
