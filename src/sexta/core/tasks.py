"""Gerenciador de tarefas: acompanha, lista e interrompe o trabalho em andamento."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

from ..memory.db import Database, utcnow


class TaskManager:
    def __init__(self, db: Database):
        self.db = db
        self._running: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._cancel_requested: set[str] = set()

    # --- Registro persistente ---------------------------------------------
    def create_record(self, task_id: str, conversation_id: str | None, preview: str) -> None:
        self.db.execute(
            "INSERT INTO tasks (id, conversation_id, status, input_preview, started_at) VALUES (?, ?, 'running', ?, ?)",
            (task_id, conversation_id, preview[:300], utcnow()),
        )

    def update_record(self, task_id: str, **fields: Any) -> None:
        if "reasons" in fields and not isinstance(fields["reasons"], str):
            fields["reasons"] = json.dumps(fields["reasons"], ensure_ascii=False)
        if not fields:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        self.db.execute(f"UPDATE tasks SET {assignments} WHERE id = :id", {**fields, "id": task_id})

    def get(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row:
            row["reasons"] = json.loads(row["reasons"] or "[]")
            row["running"] = task_id in self._running
        return row

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM tasks ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,))
        for row in rows:
            row["reasons"] = json.loads(row["reasons"] or "[]")
            row["running"] = row["id"] in self._running
        return rows

    def mark_interrupted(self) -> int:
        """Na inicialização: tarefas 'running' de uma execução anterior foram interrompidas."""
        cur = self.db.execute(
            "UPDATE tasks SET status = 'interrupted', finished_at = ? WHERE status = 'running'", (utcnow(),)
        )
        return cur.rowcount

    # --- Execução --------------------------------------------------------
    def start(self, task_id: str, coro: Coroutine[Any, Any, dict[str, Any]]) -> asyncio.Task[dict[str, Any]]:
        task = asyncio.create_task(coro, name=f"sexta-task-{task_id}")
        self._running[task_id] = task

        def _cleanup(_task: asyncio.Task[dict[str, Any]]) -> None:
            self._running.pop(task_id, None)
            self._cancel_requested.discard(task_id)

        task.add_done_callback(_cleanup)
        return task

    def running_ids(self) -> list[str]:
        return list(self._running)

    def task(self, task_id: str) -> asyncio.Task[dict[str, Any]] | None:
        return self._running.get(task_id)

    def cancel_requested(self, task_id: str) -> bool:
        return task_id in self._cancel_requested

    def cancel(self, task_id: str) -> bool:
        task = self._running.get(task_id)
        if task is None or task.done():
            return False
        # A flag garante a interrupção mesmo se o cancelamento do asyncio for
        # "engolido" (ex.: wait_for no Python 3.11 quando o futuro conclui junto).
        self._cancel_requested.add(task_id)
        task.cancel()
        return True

    def cancel_all(self) -> int:
        return sum(1 for task_id in list(self._running) if self.cancel(task_id))
