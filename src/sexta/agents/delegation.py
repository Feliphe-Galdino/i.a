"""Coordenação multiagente: a Sexta-Feira divide um pedido e delega partes a subagentes.

Como funciona:

1. A IA principal (o "planejador") decide dividir o trabalho e chama a ferramenta
   ``delegate_tasks`` com até 4 subtarefas independentes, cada uma para um agente
   especializado (programação, pesquisa, finanças…).
2. Cada subagente roda o seu próprio ciclo de IA + ferramentas, **em paralelo**, com:
   * modelo escolhido pelo MEGABRAIN para a subtarefa (respeitando orçamento);
   * apenas as ferramentas permitidas ao seu perfil (lista fechada, checada no código);
   * o MESMO executor do resto do sistema: permissões, aprovações, guardas e auditoria;
   * nunca pode delegar de novo (sem recursão).
3. Os relatórios voltam como resultado da ferramenta e a IA principal integra tudo
   numa resposta única. Custos entram no orçamento e na tarefa de origem.

As conversas dos subagentes ficam só na memória (não poluem o histórico da conversa);
o que eles fizeram fica na auditoria e no cartão "delegate_tasks" do chat.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from typing import Any

from ..core.prompts import build_system_prompt, build_turn_context
from ..llm.base import Completion, LLMError, LLMRequest, Usage
from ..memory.conversations import text_of
from ..tools.base import ToolContext
from .registry import AGENTS, AgentProfile

log = logging.getLogger(__name__)

MAX_SUBTASKS = 4
MAX_PARALLEL = 3
MAX_ROUNDS = 8
RESULT_CHARS = 6000
NO_RECURSION = {"delegate_tasks"}
# Ferramentas de leitura úteis a qualquer subagente (além das do perfil).
COMMON_TOOLS = ("memory_search",)
FINAL_TOOL_STATES = {"done", "error", "blocked", "denied", "rejected"}

SUBAGENT_ROLE = """

## Você está atuando como subagente
Você é o agente "{agent_name}", chamado pela Sexta-Feira para cuidar de UMA parte de um trabalho maior.
- Faça apenas a sua subtarefa, com as ferramentas disponíveis. Não converse com o usuário nem faça perguntas a ele: \
se faltar informação, assuma o mais razoável e diga qual suposição fez.
- Ações que precisam de autorização são pedidas ao usuário automaticamente pelo sistema; se forem negadas, siga sem elas.
- Termine com um relatório objetivo para a Sexta-Feira: resultado, fontes (com horário, quando houver), \
o que ficou pendente e riscos. Sem saudações."""


class Delegator:
    """Executa subtarefas em paralelo reaproveitando roteador, provedor e executor do orquestrador."""

    def __init__(self, orchestrator: Any):
        self.orc = orchestrator

    def allowed_tools(self, agent: AgentProfile) -> list[str]:
        names = [*agent.tools, *COMMON_TOOLS] if agent.tools else list(COMMON_TOOLS)
        out = []
        for name in names:
            if name not in NO_RECURSION and self.orc.registry.get(name) and name not in out:
                out.append(name)
        return sorted(out)  # ordem estável (prefixo em cache)

    async def run(self, subtasks: list[dict[str, str]], ctx: ToolContext) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(MAX_PARALLEL)
        parent_publish = ctx.publish
        tool_use_id = getattr(ctx, "tool_use_id", None)

        async def progress(index: int, agent: AgentProfile, status: str, **extra: Any) -> None:
            await parent_publish(
                {
                    "type": "subagent",
                    "tool_use_id": tool_use_id,
                    "index": index,
                    "agent": agent.id,
                    "agent_name": agent.name,
                    "status": status,
                    **extra,
                }
            )

        async def one(index: int, sub: dict[str, str]) -> dict[str, Any]:
            agent = AGENTS.get(sub["agent"], AGENTS["geral"])
            await progress(index, agent, "queued", task=sub["task"][:300])
            async with semaphore:
                started = time.perf_counter()
                try:
                    result = await self._run_one(index, agent, sub, ctx, progress)
                except asyncio.CancelledError:
                    await progress(index, agent, "cancelled")
                    raise
                except Exception as exc:  # noqa: BLE001 — um subagente com erro não derruba os outros
                    log.exception("Subagente %s falhou", agent.id)
                    result = {"status": "error", "result": f"Falha: {type(exc).__name__}: {exc}", "cost_usd": 0.0}
                result.update(
                    agente=agent.name,
                    subtarefa=sub["task"],
                    duracao_s=round(time.perf_counter() - started, 1),
                )
                await progress(
                    index,
                    agent,
                    result["status"],
                    cost_usd=result.get("cost_usd", 0.0),
                    preview=str(result.get("result", ""))[:300],
                )
                return result

        return list(await asyncio.gather(*(one(i, sub) for i, sub in enumerate(subtasks[:MAX_SUBTASKS]))))

    async def _run_one(self, index, agent, sub, parent_ctx, progress) -> dict[str, Any]:
        orc = self.orc
        runtime = orc.runtime.get()
        task_text = sub["task"].strip()
        decision = orc.router.decide(
            task_text,
            agent=agent,
            manual=None,
            previous_tier=None,
            priority=runtime.routing_priority,
            history_tokens=len(sub.get("context", "")) // 3,
            spent_today=orc.usage.spent_today(),
            daily_budget=runtime.daily_budget_usd,
            budget_hard_stop=runtime.budget_hard_stop,
            tier_overrides=runtime.tier_models,
        )
        if decision.blocked:
            return {
                "status": "blocked",
                "result": "Orçamento diário atingido: subtarefa não executada.",
                "cost_usd": 0.0,
            }
        if orc.offline:
            return {"status": "error", "result": "Modo offline: subagentes precisam da API.", "cost_usd": 0.0}

        allowed = self.allowed_tools(agent)
        specs = [s for s in orc.registry.specs() if s.name in allowed]
        web_search = runtime.web_search and runtime.permission_overrides.get("web.search") != "deny"
        system = build_system_prompt(
            assistant_name=runtime.assistant_name,
            user_name=runtime.user_name,
            custom_instructions=runtime.custom_instructions,
        ) + SUBAGENT_ROLE.format(agent_name=agent.name)
        context = build_turn_context(
            agent=agent,
            memories=orc.memory.relevant_for(task_text),
            timezone=orc.settings.timezone,
            web_search=web_search,
        )
        body = f"Subtarefa: {task_text}"
        if sub.get("context", "").strip():
            body += f"\n\nContexto passado pela Sexta-Feira:\n{sub['context'].strip()}"
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": context}, {"type": "text", "text": body}]}
        ]

        async def sub_publish(event: dict[str, Any]) -> None:
            # Eventos das ferramentas do subagente viram progresso no cartão da delegação;
            # os demais (memória salva, alertas…) seguem normalmente.
            if event.get("type") == "tool_status":
                status = event.get("status")
                await progress(
                    index,
                    agent,
                    "thinking" if status in FINAL_TOOL_STATES else "tool",
                    detail=f"{event.get('tool')}: {status}",
                )
            else:
                await parent_ctx.publish(event)

        ctx = dataclasses.replace(parent_ctx, publish=sub_publish, tool_use_id=None)
        cost, usage, parts, status = 0.0, Usage(), [], "done"
        await progress(index, agent, "thinking", model=decision.model)
        for round_no in range(MAX_ROUNDS + 2):
            if orc.tasks.cancel_requested(parent_ctx.task_id):
                raise asyncio.CancelledError
            completion: Completion | None = None
            async for event in orc.provider.stream(
                LLMRequest(
                    model=decision.model,
                    system=system,
                    messages=messages,
                    tools=specs,
                    effort=decision.effort,
                    web_search=web_search,
                )
            ):
                if isinstance(event, Completion):
                    completion = event
            if completion is None:
                raise LLMError("O provedor encerrou sem resposta final.")
            cost += orc.usage.record(
                completion.usage,
                provider=orc.provider.name,
                model=completion.model,
                task_id=parent_ctx.task_id,
                conversation_id=parent_ctx.conversation_id,
            )
            usage.add(completion.usage)
            messages.append({"role": "assistant", "content": completion.content})
            text = text_of(completion.content)
            if text:
                parts.append(text)
            if completion.stop_reason == "refusal":
                status = "refused"
                break
            if completion.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in completion.content if b.get("type") == "tool_use"]
            if not tool_uses:
                break
            results = []
            for block in tool_uses:
                if round_no >= MAX_ROUNDS or completion.stop_reason == "max_tokens":
                    message = "Limite de etapas do subagente atingido. Não use mais ferramentas: entregue o relatório."
                    results.append(_error(block, message))
                elif block.get("name") not in allowed:
                    results.append(
                        _error(block, f"A ferramenta {block.get('name')} não está disponível para este agente.")
                    )
                else:
                    results.append(await orc.executor.run(block, ctx))
            messages.append({"role": "user", "content": results})
        else:
            status = "incomplete"
        report = "\n\n".join(parts).strip() or "(o subagente não produziu relatório)"
        if len(report) > RESULT_CHARS:
            report = report[:RESULT_CHARS] + "\n[... relatório truncado]"
        return {
            "status": status,
            "modelo": completion.model if completion else decision.model,
            "result": report,
            "cost_usd": round(cost, 6),
            "tokens": {"entrada": usage.input_tokens + usage.cache_read_tokens, "saida": usage.output_tokens},
        }


def _error(block: dict[str, Any], message: str) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": block["id"], "content": message, "is_error": True}


def format_report(results: list[dict[str, Any]]) -> str:
    """Resultado da ferramenta para a IA principal (JSON legível)."""
    return json.dumps({"relatorios": results}, ensure_ascii=False, indent=1)
