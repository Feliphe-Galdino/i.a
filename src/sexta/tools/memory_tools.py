"""Ferramentas de memória e histórico — como a Sexta-Feira aprende e se lembra."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..memory.memories import CATEGORIES
from ..security.permissions import Risk
from .base import Assessment, Tool, ToolContext, ToolOutput

CategoryName = Literal["perfil", "preferencias", "projetos", "conhecimento", "correcoes", "tarefas", "pessoas", "geral"]


class MemorySearchArgs(BaseModel):
    query: str = Field(description="Palavras-chave do que procurar na memória.")
    category: CategoryName | None = Field(default=None, description="Filtrar por categoria (opcional).")
    limit: int = Field(default=8, ge=1, le=30)


async def memory_search(args: MemorySearchArgs, ctx: ToolContext):
    found = ctx.memory.search(args.query, category=args.category, limit=args.limit)
    if not found:
        return "Nenhuma memória encontrada para essa busca."
    return [
        {"id": m.id, "categoria": m.category, "conteudo": m.content, "tags": m.tags, "importancia": m.importance}
        for m in found
    ]


class MemorySaveArgs(BaseModel):
    content: str = Field(
        min_length=3,
        max_length=2000,
        description="Fato curto e autocontido, escrito em terceira pessoa (ex.: 'O usuário prefere exemplos em Python').",
    )
    category: CategoryName = Field(default="geral", description="; ".join(f"{k}: {v}" for k, v in CATEGORIES.items()))
    tags: list[str] = Field(default_factory=list, max_length=12, description="Palavras-chave para facilitar a busca.")
    importance: int = Field(default=3, ge=1, le=5, description="1 = trivial, 5 = essencial.")
    pinned: bool = Field(
        default=False,
        description="Se verdadeiro, a memória entra no contexto de toda conversa. Use só para fatos centrais.",
    )


async def memory_save(args: MemorySaveArgs, ctx: ToolContext):
    memory, created = ctx.memory.add(
        args.content,
        category=args.category,
        tags=args.tags,
        importance=args.importance,
        pinned=args.pinned,
        source="assistant",
        conversation_id=ctx.conversation_id,
    )
    await ctx.publish({"type": "memory_saved", "task_id": ctx.task_id, "memory": memory.to_dict(), "created": created})
    verb = "Memória salva" if created else "Memória já existia e foi reforçada"
    return f"{verb} (id {memory.id}, categoria {memory.category})."


class MemoryUpdateArgs(BaseModel):
    id: int = Field(description="ID da memória a atualizar.")
    content: str | None = Field(default=None, max_length=2000)
    category: CategoryName | None = None
    tags: list[str] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    pinned: bool | None = None


async def memory_update(args: MemoryUpdateArgs, ctx: ToolContext):
    try:
        memory = ctx.memory.update(args.id, **args.model_dump(exclude={"id"}))
    except KeyError as exc:
        return ToolOutput(str(exc), is_error=True)
    await ctx.publish({"type": "memory_saved", "task_id": ctx.task_id, "memory": memory.to_dict(), "created": False})
    return f"Memória {memory.id} atualizada."


class MemoryDeleteArgs(BaseModel):
    id: int = Field(description="ID da memória a excluir.")


def _assess_delete(args: MemoryDeleteArgs, ctx: ToolContext) -> Assessment:
    memory = ctx.memory.get(args.id)
    summary = f"Excluir a memória #{args.id}: “{memory.content[:120]}”" if memory else f"Excluir a memória #{args.id}"
    return Assessment(Risk.WRITE, summary=summary)


async def memory_delete(args: MemoryDeleteArgs, ctx: ToolContext):
    if not ctx.memory.delete(args.id):
        return ToolOutput(f"Memória {args.id} não encontrada.", is_error=True)
    await ctx.publish({"type": "memory_deleted", "task_id": ctx.task_id, "memory_id": args.id})
    return f"Memória {args.id} excluída."


class ConversationSearchArgs(BaseModel):
    query: str = Field(description="O que procurar nas conversas anteriores.")
    limit: int = Field(default=8, ge=1, le=30)


async def conversation_search(args: ConversationSearchArgs, ctx: ToolContext):
    hits = ctx.conversations.search_messages(args.query, limit=args.limit)
    if not hits:
        return "Nada encontrado nas conversas anteriores."
    return [
        {
            "conversa": h["title"],
            "conversation_id": h["conversation_id"],
            "quem": h["role"],
            "quando": h["created_at"],
            "trecho": h["snippet"],
        }
        for h in hits
    ]


class ActivityHistoryArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    tool: str | None = Field(default=None, description="Filtrar por ferramenta (opcional).")


async def activity_history(args: ActivityHistoryArgs, ctx: ToolContext):
    rows = ctx.audit.list(limit=args.limit, tool=args.tool, event="tool_executed")
    if not rows:
        return "Nenhuma atividade registrada ainda."
    return [
        {
            "quando": r["ts"],
            "ferramenta": r["tool"],
            "risco": r["risk"],
            "sucesso": bool(r["success"]),
            "resumo": r["detail"].get("summary"),
        }
        for r in rows
    ]


TOOLS = [
    Tool(
        name="memory_search",
        description="Busca na memória de longo prazo fatos sobre o usuário, preferências, projetos e conhecimentos salvos.",
        args_model=MemorySearchArgs,
        capability="memory.read",
        risk=Risk.SAFE,
        handler=memory_search,
    ),
    Tool(
        name="memory_save",
        description=(
            "Salva um fato duradouro na memória: preferências, dados de perfil, decisões de projetos, "
            "correções e instruções do usuário. Nunca salve senhas, chaves ou dados sensíveis."
        ),
        args_model=MemorySaveArgs,
        capability="memory.write",
        risk=Risk.SAFE,
        handler=memory_save,
    ),
    Tool(
        name="memory_update",
        description="Atualiza uma memória existente (por exemplo, quando o usuário corrige uma informação).",
        args_model=MemoryUpdateArgs,
        capability="memory.write",
        risk=Risk.SAFE,
        handler=memory_update,
    ),
    Tool(
        name="memory_delete",
        description="Exclui uma memória pelo ID (pede confirmação conforme as permissões).",
        args_model=MemoryDeleteArgs,
        capability="memory.write",
        risk=Risk.WRITE,
        handler=memory_delete,
        assess=_assess_delete,
    ),
    Tool(
        name="conversation_search",
        description="Procura trechos em conversas anteriores com o usuário.",
        args_model=ConversationSearchArgs,
        capability="history.read",
        risk=Risk.SAFE,
        handler=conversation_search,
    ),
    Tool(
        name="activity_history",
        description="Consulta o histórico de ações executadas pela Sexta-Feira (ferramentas usadas, quando e com que resultado).",
        args_model=ActivityHistoryArgs,
        capability="history.read",
        risk=Risk.SAFE,
        handler=activity_history,
    ),
]
