"""Registro de auditoria: tudo o que a Sexta-Feira tenta fazer fica gravado.

Cada chamada de ferramenta gera eventos (solicitação, decisão, resultado), assim você
pode revisar o que foi feito, quando, por qual tarefa e com qual autorização.
"""

from __future__ import annotations

import json
from typing import Any

from ..memory.db import Database, utcnow


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        event: str,
        *,
        task_id: str | None = None,
        conversation_id: str | None = None,
        tool: str | None = None,
        capability: str | None = None,
        risk: str | None = None,
        decision: str | None = None,
        detail: dict[str, Any] | None = None,
        success: bool | None = None,
        duration_ms: int | None = None,
    ) -> int:
        cur = self.db.execute(
            """INSERT INTO audit_log (ts, task_id, conversation_id, event, tool, capability, risk,
                   decision, detail, success, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                utcnow(),
                task_id,
                conversation_id,
                event,
                tool,
                capability,
                risk,
                decision,
                json.dumps(detail or {}, ensure_ascii=False, default=str)[:8000],
                None if success is None else int(success),
                duration_ms,
            ),
        )
        return int(cur.lastrowid)

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        event: str | None = None,
        tool: str | None = None,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if event:
            clauses.append("event = ?")
            params.append(event)
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        for row in rows:
            row["detail"] = json.loads(row["detail"] or "{}")
        return rows
