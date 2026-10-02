"""Monitoramento de consumo de API (tokens e custo estimado)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..llm.base import Usage
from ..llm.catalog import get_model
from ..memory.db import Database, utcnow


def local_day_start_utc(days_ago: int = 0) -> str:
    """Início do dia local (meia-noite) convertido para UTC ISO."""
    now = datetime.now().astimezone()
    start = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC).isoformat(timespec="seconds")


class UsageTracker:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        usage: Usage,
        *,
        provider: str,
        model: str,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> float:
        spec = get_model(model)
        cost = spec.cost(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            web_searches=usage.web_searches,
        )
        self.db.execute(
            """INSERT INTO usage_log (ts, task_id, conversation_id, provider, model, input_tokens,
                   output_tokens, cache_read_tokens, cache_write_tokens, web_searches, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                utcnow(),
                task_id,
                conversation_id,
                provider,
                model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_write_tokens,
                usage.web_searches,
                cost,
            ),
        )
        return cost

    def spent_since(self, since_iso: str) -> float:
        row = self.db.query_one("SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_log WHERE ts >= ?", (since_iso,))
        return float(row["total"]) if row else 0.0

    def task_cost(self, task_id: str) -> float:
        """Custo total de uma tarefa, incluindo subagentes e resumos ligados a ela."""
        row = self.db.query_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_log WHERE task_id = ?", (task_id,)
        )
        return float(row["total"]) if row else 0.0

    def spent_today(self) -> float:
        return self.spent_since(local_day_start_utc())

    def summary(self, days: int = 1) -> dict[str, Any]:
        since = local_day_start_utc(max(0, days - 1))
        rows = self.db.query(
            """SELECT model, COUNT(*) AS requests, SUM(input_tokens) AS input_tokens,
                      SUM(output_tokens) AS output_tokens, SUM(cache_read_tokens) AS cache_read_tokens,
                      SUM(cache_write_tokens) AS cache_write_tokens, SUM(web_searches) AS web_searches,
                      SUM(cost_usd) AS cost_usd
               FROM usage_log WHERE ts >= ? GROUP BY model ORDER BY cost_usd DESC""",
            (since,),
        )
        return {
            "since": since,
            "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 6),
            "requests": sum(r["requests"] for r in rows),
            "by_model": rows,
        }
