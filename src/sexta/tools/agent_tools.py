"""Ferramenta de coordenação multiagente (``delegate_tasks``).

A delegação em si é segura (não mexe em nada); cada ação dos subagentes passa pelo
executor com as permissões e aprovações de sempre.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..agents.delegation import MAX_SUBTASKS, format_report
from ..agents.registry import AGENTS
from ..security.permissions import Risk
from .base import Assessment, Tool, ToolContext, ToolOutput

AgentId = Literal["geral", "programacao", "pesquisa", "financas", "automacao", "organizacao", "seguranca"]
assert set(AgentId.__args__) == set(AGENTS), "atualize AgentId ao mudar os agentes"


class SubTask(BaseModel):
    agent: AgentId = Field(description="; ".join(f"{a.id} = {a.description}" for a in AGENTS.values()))
    task: str = Field(min_length=5, max_length=4000, description="O que este agente deve fazer, de forma autocontida.")
    context: str = Field(
        default="",
        max_length=8000,
        description="Informações de que ele precisa (o subagente NÃO vê esta conversa).",
    )


class DelegateArgs(BaseModel):
    tasks: list[SubTask] = Field(min_length=1, max_length=MAX_SUBTASKS)


def _assess(args: DelegateArgs, ctx: ToolContext) -> Assessment:
    names = ", ".join(AGENTS[t.agent].name for t in args.tasks)
    return Assessment(Risk.SAFE, summary=f"{len(args.tasks)} subtarefa(s) em paralelo: {names}")


async def delegate_tasks(args: DelegateArgs, ctx: ToolContext):
    delegator = getattr(ctx, "delegator", None)
    if delegator is None:
        return ToolOutput("Coordenação multiagente indisponível.", is_error=True)
    results = await delegator.run([t.model_dump() for t in args.tasks], ctx)
    return format_report(results)


TOOLS = [
    Tool(
        "delegate_tasks",
        "Divide um trabalho grande em até 4 subtarefas INDEPENDENTES e as executa em paralelo com agentes "
        "especializados, cada um com suas ferramentas. Use quando houver partes que podem andar sozinhas "
        "(ex.: pesquisar dois assuntos, analisar dados enquanto revisa código). Cada subagente só vê o que você "
        "passar em task/context. Devolve um relatório de cada um para você integrar na resposta final.",
        DelegateArgs,
        "agents.delegate",
        Risk.SAFE,
        delegate_tasks,
        _assess,
        timeout_s=900,
    ),
]
