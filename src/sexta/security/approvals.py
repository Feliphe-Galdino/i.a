"""Confirmações humanas para ações sensíveis.

Quando a política responde "perguntar", o executor cria um pedido de aprovação e
espera. A interface recebe o evento ``approval_required`` e devolve a resposta.
Sem resposta dentro do prazo, a ação é **negada** (falha segura).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..core.events import EventBus


@dataclass
class ApprovalRequest:
    id: str
    task_id: str | None
    conversation_id: str | None
    tool: str
    capability: str
    risk: str
    summary: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    future: asyncio.Future[bool] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "approval_id": self.id,
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "tool": self.tool,
            "capability": self.capability,
            "risk": self.risk,
            "summary": self.summary,
            "reason": self.reason,
            "details": self.details,
        }


class ApprovalBroker:
    def __init__(self, bus: EventBus, timeout_s: float = 300.0):
        self.bus = bus
        self.timeout_s = timeout_s
        self._pending: dict[str, ApprovalRequest] = {}

    def pending(self) -> list[dict[str, Any]]:
        return [req.public() for req in self._pending.values()]

    async def request(self, req: ApprovalRequest) -> bool:
        loop = asyncio.get_running_loop()
        req.id = req.id or uuid.uuid4().hex[:12]
        req.future = loop.create_future()
        self._pending[req.id] = req
        await self.bus.publish({"type": "approval_required", **req.public(), "timeout_s": self.timeout_s})
        try:
            return await asyncio.wait_for(asyncio.shield(req.future), timeout=self.timeout_s)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(req.id, None)
            await self.bus.publish(
                {
                    "type": "approval_resolved",
                    "approval_id": req.id,
                    "task_id": req.task_id,
                    "approved": bool(req.future.done() and not req.future.cancelled() and req.future.result()),
                }
            )

    def resolve(self, approval_id: str, approved: bool) -> bool:
        req = self._pending.get(approval_id)
        if req is None or req.future is None or req.future.done():
            return False
        req.future.set_result(bool(approved))
        return True
