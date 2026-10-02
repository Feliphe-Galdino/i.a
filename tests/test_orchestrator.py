"""Fluxo completo do MEGABRAIN com um provedor roteirizado (sem rede)."""

from __future__ import annotations

import asyncio

from conftest import assert_valid_history, collect_until_done, text, tool_use
from sexta.llm.base import Usage
from sexta.llm.offline import OfflineProvider


async def run_turn(sexta, message: str, *, on_event=None, mode: str = "auto", conversation_id=None):
    queue = sexta.bus.subscribe()
    try:
        ids = await sexta.orchestrator.submit(message, conversation_id=conversation_id, mode=mode)
        events = await collect_until_done(queue, on_event=on_event)
    finally:
        sexta.bus.unsubscribe(queue)
    return ids, events


def done_event(events):
    return next(e for e in events if e["type"] == "task_done")


async def test_simple_turn_streams_persists_and_records_usage(sexta, provider):
    provider.add([text("Olá! Como posso ajudar?")], usage=Usage(input_tokens=1000, output_tokens=200))
    ids, events = await run_turn(sexta, "Oi, Sexta-Feira!")

    types = [e["type"] for e in events]
    assert types[:2] == ["conversation_created", "task_started"]
    assert "text_delta" in types
    done = done_event(events)
    assert done["status"] == "done"
    assert done["text"] == "Olá! Como posso ajudar?"
    assert done["route"]["model"] == "claude-haiku-4-5"
    assert done["cost_usd"] == round((1000 * 1.0 + 200 * 5.0) / 1_000_000, 6)

    history = sexta.conversations.api_messages(ids["conversation_id"])
    assert [m["role"] for m in history] == ["user", "assistant"]
    # A mensagem do usuário leva o contexto do turno + o texto original
    assert history[0]["content"][0]["text"].startswith("<contexto_sexta>")
    assert history[0]["content"][1]["text"] == "Oi, Sexta-Feira!"
    assert sexta.tasks.get(ids["task_id"])["status"] == "done"
    assert sexta.usage.spent_today() > 0


async def test_system_prompt_is_frozen_per_conversation(sexta, provider):
    provider.add([text("primeira")]).add([text("segunda")])
    ids, _ = await run_turn(sexta, "Olá")
    sexta.runtime.update({"user_name": "Feliphe", "custom_instructions": "Responda em tópicos"})
    await run_turn(sexta, "Tudo bem?", conversation_id=ids["conversation_id"])
    first, second = provider.requests
    assert first.system == second.system  # mudança de configuração não altera conversa existente
    assert "Feliphe" not in second.system
    # Histórico do 2º turno começa exatamente com o do 1º (append-only)
    assert second.messages[: len(first.messages)] == first.messages


async def test_memory_save_tool_runs_without_confirmation(sexta, provider):
    provider.add(
        [
            text("Vou lembrar disso."),
            tool_use("tu_1", "memory_save", {"content": "O usuário prefere Python", "category": "preferencias"}),
        ],
        stop_reason="tool_use",
    ).add([text("Pronto, anotado!")])

    ids, events = await run_turn(sexta, "Lembre que eu prefiro Python")
    assert done_event(events)["status"] == "done"
    assert any(e["type"] == "memory_saved" for e in events)
    assert sexta.memory.search("python")[0].content == "O usuário prefere Python"
    history = sexta.conversations.api_messages(ids["conversation_id"])
    assert_valid_history(history)
    assert history[2]["content"][0]["tool_use_id"] == "tu_1"
    # A memória recém-salva entra no contexto do próximo turno
    provider.add([text("Você prefere Python.")])
    await run_turn(sexta, "Qual linguagem eu prefiro, Python ou Java?", conversation_id=ids["conversation_id"])
    assert "O usuário prefere Python" in provider.requests[-1].messages[-1]["content"][0]["text"]


async def test_write_requires_approval_and_executes_when_approved(sexta, provider, settings):
    provider.add(
        [tool_use("tu_w", "fs_write", {"path": "notas/ideia.md", "content": "# Ideia\nJarvis 2.0"})],
        stop_reason="tool_use",
    ).add([text("Arquivo criado.")])

    async def approve(event):
        if event["type"] == "approval_required":
            assert event["risk"] == "write"
            assert "ideia.md" in event["summary"]
            sexta.approvals.resolve(event["approval_id"], True)

    ids, events = await run_turn(sexta, "Crie um arquivo com minha ideia", on_event=approve)
    assert done_event(events)["status"] == "done"
    created = settings.workspace_dir / "notas" / "ideia.md"
    assert created.read_text(encoding="utf-8") == "# Ideia\nJarvis 2.0"
    audit_events = {row["event"] for row in sexta.audit.list()}
    assert {"tool_decision", "tool_approval", "tool_executed"} <= audit_events


async def test_rejected_action_is_not_executed(sexta, provider, settings):
    provider.add(
        [tool_use("tu_w", "fs_write", {"path": "x.txt", "content": "não deveria existir"})],
        stop_reason="tool_use",
    ).add([text("Tudo bem, não criei o arquivo.")])

    async def reject(event):
        if event["type"] == "approval_required":
            sexta.approvals.resolve(event["approval_id"], False)

    ids, events = await run_turn(sexta, "crie x.txt", on_event=reject)
    assert not (settings.workspace_dir / "x.txt").exists()
    result = sexta.conversations.api_messages(ids["conversation_id"])[2]["content"][0]
    assert result["is_error"] is True
    assert "não autorizou" in result["content"]


async def test_catastrophic_command_is_blocked_without_asking(sexta, provider):
    provider.add([tool_use("tu_x", "shell_run", {"command": "rm -rf /"})], stop_reason="tool_use").add(
        [text("Não posso fazer isso.")]
    )
    asked = []

    async def watch(event):
        if event["type"] == "approval_required":
            asked.append(event)

    ids, events = await run_turn(sexta, "apague tudo", on_event=watch)
    assert asked == []
    result = sexta.conversations.api_messages(ids["conversation_id"])[2]["content"][0]
    assert result["is_error"] and "Bloqueado pela segurança" in result["content"]
    assert any(row["event"] == "tool_blocked" for row in sexta.audit.list())


async def test_reading_outside_sandbox_is_denied(sexta, provider):
    provider.add([tool_use("tu_r", "fs_read", {"path": "/etc/passwd"})], stop_reason="tool_use").add([text("ok")])
    ids, _ = await run_turn(sexta, "leia /etc/passwd")
    result = sexta.conversations.api_messages(ids["conversation_id"])[2]["content"][0]
    assert result["is_error"] and "fora das pastas liberadas" in result["content"]


async def test_cancel_while_waiting_for_approval_keeps_history_valid(sexta, provider):
    provider.add([tool_use("tu_c", "shell_run", {"command": "echo oi"})], stop_reason="tool_use")

    async def cancel(event):
        if event["type"] == "approval_required":
            assert sexta.tasks.cancel(event["task_id"])

    ids, events = await run_turn(sexta, "rode echo oi", on_event=cancel)
    assert done_event(events)["status"] == "cancelled"
    history = sexta.conversations.api_messages(ids["conversation_id"])
    assert_valid_history(history)
    assert "Cancelado" in history[-1]["content"][0]["content"]
    assert sexta.tasks.get(ids["task_id"])["status"] == "cancelled"


async def test_cancel_during_streaming_persists_nothing_partial(sexta, provider):
    provider.add([text("resposta longa...")])
    provider.gate = asyncio.Event()  # o streaming nunca termina sozinho

    async def cancel(event):
        if event["type"] == "text_delta":
            sexta.tasks.cancel(event["task_id"])

    ids, events = await run_turn(sexta, "escreva um livro", on_event=cancel)
    assert done_event(events)["status"] == "cancelled"
    history = sexta.conversations.api_messages(ids["conversation_id"])
    assert [m["role"] for m in history] == ["user"]


async def test_refusal_is_reported(sexta, provider):
    provider.add([], stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"})
    _, events = await run_turn(sexta, "pedido recusado")
    done = done_event(events)
    assert done["status"] == "refused"
    assert "cyber" in done["text"]


async def test_truncated_tool_input_is_not_executed(sexta, provider, settings):
    provider.add(
        [tool_use("tu_t", "fs_write", {"path": "meio.txt", "content": "trunc"})], stop_reason="max_tokens"
    ).add([text("Vou dividir em partes menores.")])
    ids, events = await run_turn(sexta, "crie um arquivo enorme")
    assert not (settings.workspace_dir / "meio.txt").exists()
    assert not any(e["type"] == "approval_required" for e in events)
    history = sexta.conversations.api_messages(ids["conversation_id"])
    assert_valid_history(history)
    assert "truncada" in history[2]["content"][0]["content"]


async def test_tool_round_limit(sexta, provider, settings):
    settings.max_tool_rounds = 2
    for i in range(3):
        provider.add([tool_use(f"tu_{i}", "memory_search", {"query": "x"})], stop_reason="tool_use")
    provider.add([text("Resumo do que foi feito.")])
    ids, events = await run_turn(sexta, "procure várias vezes")
    assert done_event(events)["status"] == "done"
    history = sexta.conversations.api_messages(ids["conversation_id"])
    assert_valid_history(history)
    assert "Limite de etapas" in history[-2]["content"][0]["content"]


async def test_manual_mode_and_tools_are_sent(sexta, provider):
    provider.add([text("ok")])
    await run_turn(sexta, "oi", mode="profundo")
    request = provider.requests[0]
    assert request.model == "claude-opus-5-5"
    assert {t.name for t in request.tools} >= {"memory_save", "fs_read", "shell_run"}
    assert [t.name for t in request.tools] == sorted(t.name for t in request.tools)
    assert request.web_search is True


async def test_web_search_respects_settings(sexta, provider):
    sexta.runtime.update({"web_search": False})
    provider.add([text("ok")])
    await run_turn(sexta, "notícias de hoje")
    assert provider.requests[0].web_search is False


async def test_budget_hard_stop_blocks_call(sexta, provider):
    sexta.runtime.update({"daily_budget_usd": 0.000001, "budget_hard_stop": True})
    provider.add([text("primeira")], usage=Usage(input_tokens=10_000, output_tokens=10_000))
    await run_turn(sexta, "oi")
    _, events = await run_turn(sexta, "oi de novo")
    assert done_event(events)["status"] == "blocked"
    assert len(provider.requests) == 1


async def test_offline_provider(settings):
    from sexta.container import build_sexta

    sexta = build_sexta(settings, provider=OfflineProvider())
    try:
        _, events = await run_turn(sexta, "olá")
        done = done_event(events)
        assert done["status"] == "done"
        assert "modo offline" in done["text"]
        assert done["route"]["model"] == "offline"
    finally:
        sexta.close()


async def test_two_messages_same_conversation_are_serialized(sexta, provider):
    provider.add([text("um")]).add([text("dois")])
    queue = sexta.bus.subscribe()
    first = await sexta.orchestrator.submit("primeira")
    second = await sexta.orchestrator.submit("segunda", conversation_id=first["conversation_id"])
    done = []
    while len(done) < 2:
        event = await asyncio.wait_for(queue.get(), 5)
        if event["type"] == "task_done":
            done.append(event["task_id"])
    assert done == [first["task_id"], second["task_id"]]
    history = sexta.conversations.api_messages(first["conversation_id"])
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


async def test_voice_channel_reaches_context_and_events(sexta, provider):
    provider.add([text("São três da tarde.")])
    queue = sexta.bus.subscribe()
    try:
        await sexta.orchestrator.submit("que horas são?", channel="voz")
        events = await collect_until_done(queue)
    finally:
        sexta.bus.unsubscribe(queue)
    assert all(e.get("channel") == "voz" for e in events if e.get("task_id"))
    context = provider.requests[0].messages[-1]["content"][0]["text"]
    assert "canal: voz" in context


async def test_text_channel_is_default_and_invalid_channel_falls_back(sexta, provider):
    provider.add([text("ok")]).add([text("ok")])
    _, events = await run_turn(sexta, "oi")
    assert done_event(events)["channel"] == "texto"
    queue = sexta.bus.subscribe()
    try:
        await sexta.orchestrator.submit("oi", channel="telepatia")
        events = await collect_until_done(queue)
    finally:
        sexta.bus.unsubscribe(queue)
    assert done_event(events)["channel"] == "texto"
    assert "canal: voz" not in provider.requests[-1].messages[-1]["content"][0]["text"]
