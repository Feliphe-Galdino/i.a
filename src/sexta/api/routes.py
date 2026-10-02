"""Rotas REST da Sexta-Feira (todas exigem o token de acesso)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from ..container import Sexta
from ..intel.feeds import CATEGORY_LABELS
from ..llm.catalog import MODELS, Tier
from ..security.permissions import AUTONOMY_LEVELS, CAPABILITIES
from ..tools.system_tools import system_snapshot
from .deps import get_sexta, require_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


# --- Status -------------------------------------------------------------------


@router.get("/status")
async def status(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    runtime = sexta.runtime.get()
    spent = sexta.usage.spent_today()
    return {
        "provider": sexta.provider.name,
        "online": sexta.provider.name != "offline",
        "running_tasks": sexta.tasks.running_ids(),
        "pending_approvals": len(sexta.approvals.pending()),
        "clients": sexta.bus.subscriber_count,
        "autonomy_level": runtime.autonomy_level,
        "autonomy_name": AUTONOMY_LEVELS[runtime.autonomy_level]["name"],
        "spent_today_usd": round(spent, 4),
        "daily_budget_usd": runtime.daily_budget_usd,
        "memory": sexta.memory.stats(),
        "voice": sexta.voice.status(),
        "system": await asyncio.to_thread(system_snapshot, str(sexta.settings.workspace_dir)),
    }


@router.get("/usage")
def usage(days: int = Query(1, ge=1, le=90), sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    return sexta.usage.summary(days)


# --- Chat ---------------------------------------------------------------------


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    conversation_id: str | None = None
    mode: Literal["auto", "rapido", "equilibrado", "profundo"] = "auto"
    channel: Literal["texto", "voz"] = "texto"
    wait: bool = False


@router.post("/chat")
async def chat(body: ChatIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    try:
        ids = await sexta.orchestrator.submit(
            body.text, conversation_id=body.conversation_id, mode=body.mode, channel=body.channel
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not body.wait:
        return ids
    result = await sexta.orchestrator.wait(ids["task_id"])
    return {**ids, **result}


# --- Conversas --------------------------------------------------------------


@router.get("/conversations")
def list_conversations(
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), sexta: Sexta = Depends(get_sexta)
) -> list[dict[str, Any]]:
    return sexta.conversations.list(limit=limit, offset=offset)


@router.get("/conversations/{conv_id}")
def get_conversation(conv_id: str, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    conv = sexta.conversations.get(conv_id)
    if conv is None:
        raise HTTPException(404, "Conversa não encontrada.")
    conv.pop("system_prompt", None)
    return {"conversation": conv, "messages": sexta.conversations.view(conv_id)}


class ConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.patch("/conversations/{conv_id}")
def rename_conversation(conv_id: str, body: ConversationPatch, sexta: Sexta = Depends(get_sexta)) -> dict[str, str]:
    if sexta.conversations.get(conv_id) is None:
        raise HTTPException(404, "Conversa não encontrada.")
    sexta.conversations.rename(conv_id, body.title)
    return {"status": "ok"}


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str, sexta: Sexta = Depends(get_sexta)) -> dict[str, str]:
    for task_id in sexta.tasks.running_ids():
        record = sexta.tasks.get(task_id)
        if record and record["conversation_id"] == conv_id:
            raise HTTPException(409, "Há uma tarefa em andamento nesta conversa. Interrompa-a primeiro.")
    if not sexta.conversations.delete(conv_id):
        raise HTTPException(404, "Conversa não encontrada.")
    sexta.audit.record("conversation_deleted", conversation_id=conv_id)
    return {"status": "ok"}


@router.get("/search")
def search_messages(
    q: str = Query(min_length=1), limit: int = Query(20, ge=1, le=100), sexta: Sexta = Depends(get_sexta)
):
    return sexta.conversations.search_messages(q, limit=limit)


# --- Memórias ------------------------------------------------------------------


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = "geral"
    tags: list[str] = Field(default_factory=list)
    importance: int = Field(default=3, ge=1, le=5)
    pinned: bool = False


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, max_length=2000)
    category: str | None = None
    tags: list[str] | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    pinned: bool | None = None


@router.get("/memories")
def list_memories(
    category: str | None = None,
    q: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sexta: Sexta = Depends(get_sexta),
) -> list[dict[str, Any]]:
    return [m.to_dict() for m in sexta.memory.list(category=category, query=q, limit=limit, offset=offset)]


@router.get("/memories/stats")
def memory_stats(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    from ..memory.memories import CATEGORIES

    return {**sexta.memory.stats(), "categories": CATEGORIES}


@router.get("/memories/export")
def export_memories(sexta: Sexta = Depends(get_sexta)) -> Response:
    payload = json.dumps(sexta.memory.export(), ensure_ascii=False, indent=2)
    sexta.audit.record("memories_exported")
    return Response(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="sexta-feira-memorias.json"'},
    )


@router.post("/memories/import")
async def import_memories(request: Request, sexta: Sexta = Depends(get_sexta)) -> dict[str, int]:
    try:
        payload = await request.json()
        result = sexta.memory.import_(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Arquivo de memórias inválido: {exc}") from exc
    sexta.audit.record("memories_imported", detail=result)
    return result


@router.post("/memories")
def create_memory(body: MemoryIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    memory, created = sexta.memory.add(
        body.content,
        category=body.category,
        tags=body.tags,
        importance=body.importance,
        pinned=body.pinned,
        source="user",
    )
    return {"memory": memory.to_dict(), "created": created}


@router.get("/memories/{memory_id}")
def get_memory(memory_id: int, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    memory = sexta.memory.get(memory_id)
    if memory is None:
        raise HTTPException(404, "Memória não encontrada.")
    return memory.to_dict()


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: int, body: MemoryPatch, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    try:
        return sexta.memory.update(memory_id, **body.model_dump(exclude_unset=True)).to_dict()
    except KeyError as exc:
        raise HTTPException(404, "Memória não encontrada.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, sexta: Sexta = Depends(get_sexta)) -> dict[str, str]:
    if not sexta.memory.delete(memory_id):
        raise HTTPException(404, "Memória não encontrada.")
    sexta.audit.record("memory_deleted", detail={"id": memory_id})
    return {"status": "ok"}


@router.delete("/memories")
def delete_all_memories(confirm: str = Query(""), sexta: Sexta = Depends(get_sexta)) -> dict[str, int]:
    if confirm != "APAGAR TUDO":
        raise HTTPException(400, "Para apagar todas as memórias envie confirm=APAGAR TUDO.")
    count = sexta.memory.delete_all()
    sexta.audit.record("memories_wiped", detail={"count": count})
    return {"deleted": count}


# --- Tarefas, aprovações e auditoria -------------------------------------


@router.get("/tasks")
def list_tasks(limit: int = Query(30, ge=1, le=200), sexta: Sexta = Depends(get_sexta)) -> list[dict[str, Any]]:
    return sexta.tasks.recent(limit)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    return {"cancelled": sexta.tasks.cancel(task_id)}


class CancelAllIn(BaseModel):
    panic: bool = False


@router.post("/tasks/cancel_all")
def cancel_all(body: CancelAllIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    count = sexta.tasks.cancel_all()
    if body.panic:
        sexta.runtime.update({"autonomy_level": 0})
    sexta.audit.record("panic" if body.panic else "cancel_all", detail={"cancelled": count})
    return {"cancelled": count, "autonomy_level": sexta.runtime.get().autonomy_level}


@router.get("/approvals")
def pending_approvals(sexta: Sexta = Depends(get_sexta)) -> list[dict[str, Any]]:
    return sexta.approvals.pending()


class ApprovalIn(BaseModel):
    approved: bool


@router.post("/approvals/{approval_id}")
def resolve_approval(approval_id: str, body: ApprovalIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, bool]:
    if not sexta.approvals.resolve(approval_id, body.approved):
        raise HTTPException(404, "Pedido de aprovação não encontrado ou já resolvido.")
    return {"ok": True}


@router.get("/audit")
def audit_log(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    event: str | None = None,
    tool: str | None = None,
    sexta: Sexta = Depends(get_sexta),
) -> list[dict[str, Any]]:
    return sexta.audit.list(limit=limit, offset=offset, event=event, tool=tool)


# --- Configurações -----------------------------------------------------------


@router.get("/settings")
def get_settings(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    s = sexta.settings
    return {
        "runtime": sexta.runtime.get().model_dump(),
        "capabilities": CAPABILITIES,
        "autonomy_levels": AUTONOMY_LEVELS,
        "tiers": {t.value: {"label": t.label, "default_model": sexta.router.tier_models[t]} for t in Tier},
        "models": {
            m.id: {"label": m.label, "input": m.input_per_mtok, "output": m.output_per_mtok} for m in MODELS.values()
        },
        "tools": [
            {"name": t.name, "description": t.description, "capability": t.capability, "risk": t.risk.value}
            for t in sexta.registry.all()
        ],
        "paths": {
            "workspace": str(s.workspace_dir),
            "data": str(s.data_dir),
            "extra_roots": [str(p) for p in s.extra_roots],
        },
        "provider": sexta.provider.name,
        "news_categories": CATEGORY_LABELS,
    }


@router.put("/settings")
def update_settings(changes: dict[str, Any], sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    before = sexta.runtime.get().model_dump()
    try:
        updated = sexta.runtime.update(changes)
    except ValueError as exc:
        raise HTTPException(400, f"Configuração inválida: {exc}") from exc
    after = updated.model_dump()
    changed = {key for key in after if after[key] != before.get(key)}
    sexta.audit.record("settings_changed", detail={"changes": {k: after[k] for k in changed}})
    if sexta.voice.loop is not None:
        sexta.voice.apply_settings(changed)
    return after


# --- Sistema (Windows) ---------------------------------------------------------


@router.get("/system/autostart")
def autostart_status(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    return sexta.autostart.status()


class AutostartIn(BaseModel):
    enabled: bool
    window: bool = False


@router.put("/system/autostart")
def set_autostart(body: AutostartIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    if not sexta.autostart.supported:
        raise HTTPException(400, "Iniciar com o sistema está disponível apenas no Windows.")
    status = sexta.autostart.enable(window=body.window) if body.enabled else sexta.autostart.disable()
    sexta.audit.record("autostart_changed", detail={"enabled": body.enabled})
    return status


@router.post("/system/shutdown")
def shutdown(request: Request, sexta: Sexta = Depends(get_sexta)) -> dict[str, str]:
    server = getattr(request.app.state, "server", None)
    sexta.audit.record("shutdown")
    if server is None:
        raise HTTPException(503, "Servidor não foi iniciado pela linha de comando.")
    sexta.tasks.cancel_all()
    server.should_exit = True
    return {"status": "encerrando"}
