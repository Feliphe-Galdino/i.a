"""Fixtures compartilhadas: configuração isolada e um provedor de IA roteirizado."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from sexta.config import Settings
from sexta.container import Sexta, build_sexta
from sexta.llm.base import Completion, LLMEvent, LLMRequest, TextDelta, ToolUseStarted, Usage

TOKEN = "token-de-teste-123456"


class ScriptedProvider:
    """Provedor falso: devolve respostas pré-definidas e registra as requisições."""

    name = "anthropic"

    def __init__(self, turns: list[dict[str, Any]] | None = None):
        self.turns = list(turns or [])
        self.requests: list[LLMRequest] = []
        self.gate: asyncio.Event | None = None  # permite "travar" o streaming nos testes

    def add(self, content: list[dict[str, Any]], stop_reason: str = "end_turn", **extra: Any) -> ScriptedProvider:
        self.turns.append({"content": content, "stop_reason": stop_reason, **extra})
        return self

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        self.requests.append(request)
        if not self.turns:
            raise AssertionError("ScriptedProvider sem respostas restantes")
        turn = self.turns.pop(0)
        for block in turn["content"]:
            if block["type"] == "text":
                yield TextDelta(block["text"])
            elif block["type"] == "tool_use":
                yield ToolUseStarted(block["id"], block["name"])
        if self.gate is not None:
            await self.gate.wait()
        yield Completion(
            content=turn["content"],
            stop_reason=turn["stop_reason"],
            model=request.model,
            usage=turn.get("usage", Usage(input_tokens=100, output_tokens=50)),
            stop_details=turn.get("stop_details"),
        )


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def tool_use(tool_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": payload}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "SEXTA_ANTHROPIC_API_KEY", "SEXTA_DATA_DIR", "SEXTA_WORKSPACE_DIR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        access_token=TOKEN,
        approval_timeout_s=5,
        daily_budget_usd=5.0,
        background_services=False,
    )


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def sexta(settings: Settings, provider: ScriptedProvider) -> Sexta:
    instance = build_sexta(settings, provider=provider)
    yield instance
    instance.close()


def assert_valid_history(messages: list[dict[str, Any]]) -> None:
    """Toda chamada de ferramenta precisa ter resultado na mensagem seguinte."""
    assert messages[0]["role"] == "user"
    for index, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        ids = {b["id"] for b in message["content"] if b.get("type") == "tool_use"}
        if not ids:
            continue
        assert index + 1 < len(messages), "tool_use sem tool_result no final do histórico"
        following = messages[index + 1]
        assert following["role"] == "user"
        result_ids = {b["tool_use_id"] for b in following["content"] if b.get("type") == "tool_result"}
        assert ids <= result_ids, f"tool_use sem resultado: {ids - result_ids}"


async def collect_until_done(queue: asyncio.Queue, *, timeout: float = 5.0, on_event=None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    async def _loop() -> None:
        while True:
            event = await queue.get()
            events.append(event)
            if on_event is not None:
                await on_event(event)
            if event["type"] == "task_done":
                return

    await asyncio.wait_for(_loop(), timeout=timeout)
    return events
