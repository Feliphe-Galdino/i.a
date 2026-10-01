"""Barramento de eventos: o "sistema nervoso" que liga o núcleo à interface.

Tarefas publicam eventos (texto em streaming, chamadas de ferramenta, pedidos de
aprovação...) e qualquer interface conectada (web hoje; voz, celular amanhã) os
recebe. As tarefas não dependem de haver alguém conectado.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


class EventBus:
    def __init__(self, queue_size: int = 2000):
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._queue_size = queue_size

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: dict[str, Any]) -> None:
        event.setdefault("ts", datetime.now(UTC).isoformat(timespec="milliseconds"))
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("Assinante lento: evento %s descartado", event.get("type"))
