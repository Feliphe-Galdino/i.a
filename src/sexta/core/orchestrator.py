"""Orquestrador — o ciclo de raciocínio e ação da Sexta-Feira (MEGABRAIN).

Para cada mensagem do usuário:

    rotear (agente + modelo) → montar contexto (memórias) → chamar a IA em streaming
      ↳ se a IA pedir ferramentas: executor (permissões/aprovação/auditoria) → resultados
      ↳ repetir até a resposta final (com limite de etapas)
    → registrar custo → publicar eventos para a interface

Garantias importantes:
* **Histórico sempre válido**: toda chamada de ferramenta gravada recebe um
  resultado — mesmo em caso de erro, recusa, truncamento ou cancelamento.
* **Append-only**: nada do histórico é editado depois de gravado.
* **Uma tarefa por conversa por vez** (lock), várias conversas em paralelo.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from ..agents.registry import select_agent
from ..config import Settings
from ..llm.base import (
    Completion,
    LLMError,
    LLMProvider,
    LLMRequest,
    StreamReset,
    TextDelta,
    ThinkingDelta,
    ToolUseStarted,
    Usage,
)
from ..llm.catalog import OFFLINE_MODEL, Tier
from ..memory.conversations import ConversationService, make_title, text_of
from ..memory.db import utcnow
from ..memory.memories import MemoryService
from ..security.audit import AuditLog
from ..security.guards import PathSandbox
from ..tools.base import ToolContext, ToolRegistry
from ..tools.executor import ToolExecutor
from .events import EventBus
from .prompts import build_system_prompt, build_turn_context
from .router import Router, strip_manual_prefix
from .runtime_settings import RuntimeSettings, RuntimeSettingsStore
from .tasks import TaskManager
from .usage import UsageTracker

log = logging.getLogger(__name__)

MODES = {"auto", "rapido", "equilibrado", "profundo"}
CHANNELS = {"texto", "voz"}


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        runtime: RuntimeSettingsStore,
        conversations: ConversationService,
        memory: MemoryService,
        usage: UsageTracker,
        audit: AuditLog,
        registry: ToolRegistry,
        executor: ToolExecutor,
        router: Router,
        provider: LLMProvider,
        bus: EventBus,
        tasks: TaskManager,
    ):
        self.settings = settings
        self.runtime = runtime
        self.conversations = conversations
        self.memory = memory
        self.usage = usage
        self.audit = audit
        self.registry = registry
        self.executor = executor
        self.router = router
        self.provider = provider
        self.bus = bus
        self.tasks = tasks
        self._locks: dict[str, asyncio.Lock] = {}
        # Serviços extras repassados às ferramentas (preenchidos pelo container)
        self.services: dict[str, Any] = {}

    @property
    def offline(self) -> bool:
        return self.provider.name == "offline"

    def sandbox(self, runtime: RuntimeSettings) -> PathSandbox:
        roots = [self.settings.workspace_dir, *self.settings.extra_roots]
        roots += [p for p in (_as_path(r) for r in runtime.fs_roots) if p is not None]
        return PathSandbox(roots=roots, blocked=[self.settings.data_dir], default_dir=self.settings.workspace_dir)

    # ------------------------------------------------------------------
    async def submit(
        self,
        text: str,
        *,
        conversation_id: str | None = None,
        mode: str = "auto",
        channel: str = "texto",
    ) -> dict[str, str]:
        text = (text or "").strip()
        if not text:
            raise ValueError("Mensagem vazia.")
        if len(text) > 200_000:
            raise ValueError("Mensagem longa demais (máx. 200 mil caracteres).")
        mode = mode if mode in MODES else "auto"
        channel = channel if channel in CHANNELS else "texto"
        if conversation_id:
            if self.conversations.get(conversation_id) is None:
                raise KeyError("Conversa não encontrada.")
        else:
            runtime = self.runtime.get()
            system_prompt = build_system_prompt(
                assistant_name=runtime.assistant_name,
                user_name=runtime.user_name,
                custom_instructions=runtime.custom_instructions,
            )
            title_text, _ = strip_manual_prefix(text)
            conversation_id = self.conversations.create(
                system_prompt=system_prompt, title=make_title(title_text or text)
            )["id"]
            await self.bus.publish(
                {
                    "type": "conversation_created",
                    "conversation_id": conversation_id,
                    "title": make_title(title_text or text),
                }
            )
        task_id = uuid.uuid4().hex[:12]
        self.tasks.create_record(task_id, conversation_id, text)
        self.tasks.start(task_id, self._run(task_id, conversation_id, text, mode, channel))
        return {"task_id": task_id, "conversation_id": conversation_id}

    async def wait(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.task(task_id)
        if task is None:
            record = self.tasks.get(task_id)
            if record is None:
                raise KeyError("Tarefa não encontrada.")
            return {"task_id": task_id, "status": record["status"], "text": None}
        return await asyncio.shield(task)

    # ------------------------------------------------------------------
    async def _run(self, task_id: str, conv_id: str, raw_text: str, mode: str, channel: str) -> dict[str, Any]:
        lock = self._locks.setdefault(conv_id, asyncio.Lock())
        try:
            await lock.acquire()
        except asyncio.CancelledError:
            # Cancelada enquanto esperava outra tarefa da mesma conversa terminar.
            self.tasks.update_record(task_id, status="cancelled", finished_at=utcnow())
            result = {"task_id": task_id, "status": "cancelled", "error": None, "text": "", "cost_usd": 0.0}
            await self.bus.publish({"type": "task_done", "conversation_id": conv_id, "channel": channel, **result})
            return result
        try:
            return await self._run_locked(task_id, conv_id, raw_text, mode, channel)
        finally:
            lock.release()

    async def _run_locked(self, task_id: str, conv_id: str, raw_text: str, mode: str, channel: str) -> dict[str, Any]:
        async def publish(event: dict[str, Any]) -> None:
            await self.bus.publish({**event, "task_id": task_id, "conversation_id": conv_id, "channel": channel})

        runtime = self.runtime.get()
        conv = self.conversations.get(conv_id)
        assert conv is not None

        text, manual = strip_manual_prefix(raw_text)
        text = text.strip() or raw_text
        if manual is None and mode != "auto":
            manual = Tier(mode)

        agent, _ = select_agent(text)
        previous_tier = Tier(conv["last_tier"]) if conv.get("last_tier") else None
        decision = self.router.decide(
            text,
            agent=agent,
            manual=manual,
            previous_tier=previous_tier,
            priority=runtime.routing_priority,
            history_tokens=self.conversations.history_chars(conv_id) // 3,
            spent_today=self.usage.spent_today(),
            daily_budget=runtime.daily_budget_usd,
            budget_hard_stop=runtime.budget_hard_stop,
            tier_overrides=runtime.tier_models,
        )
        if self.offline:
            decision.model = OFFLINE_MODEL.id
            decision.effort = None
            decision.reasons.append("modo offline (sem chave de API)")

        self.tasks.update_record(
            task_id,
            agent=decision.agent_id,
            tier=decision.tier.value,
            model=decision.model,
            effort=decision.effort,
            reasons=decision.reasons,
        )
        await publish({"type": "task_started", "route": decision.public(), "input": text[:500]})

        status, error, final_parts = "done", None, []
        total_usage, total_cost = Usage(), 0.0
        pending: list[dict[str, Any]] = []
        partial_results: list[dict[str, Any]] = []

        if decision.blocked:
            status = "blocked"
            error = "Orçamento diário atingido. Aumente o limite nas Configurações ou desative o bloqueio."
            await publish({"type": "error", "message": error})
            return await self._finish(publish, task_id, status, error, "", total_usage, total_cost, decision)

        web_search = runtime.web_search and runtime.permission_overrides.get("web.search") != "deny"
        memories = self.memory.relevant_for(text)
        context = build_turn_context(
            agent=agent, memories=memories, timezone=self.settings.timezone, web_search=web_search, channel=channel
        )
        self.conversations.append(
            conv_id,
            role="user",
            kind="user",
            content=[{"type": "text", "text": context}, {"type": "text", "text": text}],
            display_text=text,
            task_id=task_id,
        )
        self.conversations.set_route(conv_id, tier=decision.tier.value, model=decision.model)
        await publish(
            {
                "type": "context",
                "memories": [{"id": m.id, "content": m.content, "category": m.category} for m in memories],
                "web_search": web_search,
            }
        )

        tools = [] if self.offline else self.registry.specs()
        ctx = ToolContext(
            settings=self.settings,
            runtime=runtime,
            sandbox=self.sandbox(runtime),
            memory=self.memory,
            conversations=self.conversations,
            audit=self.audit,
            publish=publish,
            task_id=task_id,
            conversation_id=conv_id,
            **self.services,
        )

        max_rounds = self.settings.max_tool_rounds
        try:
            for round_no in range(max_rounds + 2):
                self._check_cancel(task_id)
                request = LLMRequest(
                    model=decision.model,
                    system=conv["system_prompt"],
                    messages=self.conversations.api_messages(conv_id),
                    tools=tools,
                    effort=decision.effort,
                    web_search=web_search and not self.offline,
                )
                completion: Completion | None = None
                await publish({"type": "llm_call", "round": round_no, "model": decision.model})
                async for event in self.provider.stream(request):
                    if isinstance(event, TextDelta):
                        await publish({"type": "text_delta", "text": event.text})
                    elif isinstance(event, ThinkingDelta):
                        await publish({"type": "thinking_delta", "text": event.text})
                    elif isinstance(event, ToolUseStarted):
                        await publish(
                            {
                                "type": "tool_started",
                                "tool_use_id": event.id,
                                "tool": event.name,
                                "server": event.server,
                            }
                        )
                    elif isinstance(event, StreamReset):
                        await publish({"type": "stream_reset", "reason": event.reason})
                    elif isinstance(event, Completion):
                        completion = event
                if completion is None:
                    raise LLMError("O provedor encerrou sem resposta final.")

                cost = self.usage.record(
                    completion.usage,
                    provider=self.provider.name,
                    model=completion.model,
                    task_id=task_id,
                    conversation_id=conv_id,
                )
                total_cost += cost
                total_usage.add(completion.usage)
                await publish(
                    {
                        "type": "usage",
                        "cost_usd": round(total_cost, 6),
                        "usage": vars(total_usage).copy(),
                        "model": completion.model,
                    }
                )

                self.conversations.append(
                    conv_id,
                    role="assistant",
                    kind="assistant",
                    content=completion.content,
                    display_text=text_of(completion.content),
                    model=completion.model,
                    task_id=task_id,
                )
                tool_uses = [b for b in completion.content if b.get("type") == "tool_use"]
                pending, partial_results = tool_uses, []
                round_text = text_of(completion.content)
                if round_text:
                    final_parts.append(round_text)
                await publish(
                    {
                        "type": "assistant_message",
                        "text": round_text,
                        "stop_reason": completion.stop_reason,
                        "model": completion.model,
                    }
                )

                if completion.stop_reason == "refusal":
                    category = (completion.stop_details or {}).get("category")
                    note = "O modelo recusou esta solicitação pelos filtros de segurança" + (
                        f" (categoria: {category})." if category else "."
                    )
                    final_parts.append(note)
                    await publish({"type": "refusal", "message": note, "details": completion.stop_details})
                    status = "refused"
                    if pending:
                        self._append_results(
                            conv_id, task_id, _error_results(pending, "Interrompido por recusa do modelo.")
                        )
                        pending = []
                    break

                if completion.stop_reason == "pause_turn":
                    continue  # turno longo de ferramenta do servidor: reenviar para continuar

                if not tool_uses:
                    break

                if completion.stop_reason == "max_tokens":
                    results = _error_results(
                        tool_uses,
                        "A entrada desta ferramenta foi truncada (limite de tokens). Divida em partes menores.",
                    )
                elif round_no >= max_rounds:
                    results = _error_results(
                        tool_uses,
                        "Limite de etapas desta tarefa atingido. Não use mais ferramentas: resuma o que foi feito e o que falta.",
                    )
                else:
                    for block in tool_uses:
                        self._check_cancel(task_id)
                        partial_results.append(await self.executor.run(block, ctx))
                    self._check_cancel(task_id)
                    results = partial_results
                self._append_results(conv_id, task_id, results)
                pending, partial_results = [], []
            else:
                status = "incomplete"
        except asyncio.CancelledError:
            status, error = "cancelled", "Tarefa interrompida pelo usuário."
            self._close_pending(conv_id, task_id, pending, partial_results, "Cancelado pelo usuário antes de concluir.")
            await publish({"type": "task_cancelled"})
        except LLMError as exc:
            status, error = "error", str(exc)
            self._close_pending(conv_id, task_id, pending, partial_results, "Erro interno ao executar.")
            await publish({"type": "error", "message": error, "retryable": exc.retryable})
        except Exception as exc:  # noqa: BLE001 — a tarefa nunca derruba o servidor
            log.exception("Falha na tarefa %s", task_id)
            status, error = "error", f"Erro inesperado: {type(exc).__name__}: {exc}"
            self._close_pending(conv_id, task_id, pending, partial_results, "Erro interno ao executar.")
            await publish({"type": "error", "message": error})

        return await self._finish(
            publish, task_id, status, error, "\n\n".join(final_parts), total_usage, total_cost, decision
        )

    # ------------------------------------------------------------------
    def _check_cancel(self, task_id: str) -> None:
        if self.tasks.cancel_requested(task_id):
            raise asyncio.CancelledError

    def _append_results(self, conv_id: str, task_id: str, results: list[dict[str, Any]]) -> None:
        self.conversations.append(conv_id, role="user", kind="tool_results", content=results, task_id=task_id)

    def _close_pending(
        self,
        conv_id: str,
        task_id: str,
        pending: list[dict[str, Any]],
        partial: list[dict[str, Any]],
        message: str,
    ) -> None:
        if not pending:
            return
        done = {r["tool_use_id"] for r in partial}
        results = list(partial) + _error_results([b for b in pending if b["id"] not in done], message)
        self._append_results(conv_id, task_id, results)

    async def _finish(self, publish, task_id, status, error, text, usage, cost, decision) -> dict[str, Any]:
        cost = max(cost, self.usage.task_cost(task_id))  # inclui o que os subagentes gastaram
        self.tasks.update_record(task_id, status=status, error=error, cost_usd=round(cost, 6), finished_at=utcnow())
        result = {
            "task_id": task_id,
            "status": status,
            "error": error,
            "text": text,
            "cost_usd": round(cost, 6),
            "usage": vars(usage).copy(),
            "route": decision.public(),
        }
        await publish({"type": "task_done", **result})
        return result


def _error_results(tool_uses: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    return [{"type": "tool_result", "tool_use_id": b["id"], "content": message, "is_error": True} for b in tool_uses]


def _as_path(value: str) -> Path | None:
    value = (value or "").strip()
    return Path(value).expanduser() if value else None
