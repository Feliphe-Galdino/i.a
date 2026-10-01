"""WebSocket: canal em tempo real entre a interface e o núcleo.

Mensagens do cliente:
    {"type": "chat", "text": "...", "conversation_id": "...", "mode": "auto"}
    {"type": "cancel", "task_id": "..."}
    {"type": "approval", "approval_id": "...", "approved": true}
    {"type": "ping"}

O servidor envia todos os eventos do barramento (texto em streaming, ferramentas,
aprovações, custos, conclusão de tarefas...).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..container import Sexta
from .deps import websocket_authorized

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    if not websocket_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    sexta: Sexta = ws.app.state.sexta
    queue = sexta.bus.subscribe()

    async def pump() -> None:
        while True:
            event = await queue.get()
            await ws.send_json(event)

    sender = asyncio.create_task(pump())
    try:
        await ws.send_json(
            {
                "type": "hello",
                "provider": sexta.provider.name,
                "running_tasks": sexta.tasks.running_ids(),
                "pending_approvals": sexta.approvals.pending(),
            }
        )
        while True:
            message = await ws.receive_json()
            reply = await _handle(sexta, message)
            if reply is not None:
                await ws.send_json(reply)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("Erro no WebSocket")
    finally:
        sexta.bus.unsubscribe(queue)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender


async def _handle(sexta: Sexta, message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return {"type": "error", "message": "Mensagem inválida."}
    kind = message.get("type")
    if kind == "ping":
        return {"type": "pong"}
    if kind == "chat":
        try:
            ids = await sexta.orchestrator.submit(
                str(message.get("text", "")),
                conversation_id=message.get("conversation_id") or None,
                mode=str(message.get("mode") or "auto"),
            )
        except (KeyError, ValueError) as exc:
            return {"type": "error", "message": str(exc).strip("'\""), "client_ref": message.get("client_ref")}
        return {"type": "task_accepted", **ids, "client_ref": message.get("client_ref")}
    if kind == "cancel":
        return {
            "type": "cancel_result",
            "task_id": message.get("task_id"),
            "cancelled": sexta.tasks.cancel(str(message.get("task_id"))),
        }
    if kind == "approval":
        ok = sexta.approvals.resolve(str(message.get("approval_id")), bool(message.get("approved")))
        return {"type": "approval_ack", "approval_id": message.get("approval_id"), "ok": ok}
    return {"type": "error", "message": f"Tipo de mensagem desconhecido: {kind}"}
