"""Cache das fontes externas (memória + banco), com fallback para o último dado bom.

Se uma fonte falhar, devolvemos o último resultado guardado marcado como ``stale`` —
melhor um dado de 20 minutos atrás (com o horário visível) do que nenhum.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..memory.db import Database


def _now() -> datetime:
    return datetime.now(UTC)


class IntelCache:
    def __init__(self, db: Database):
        self.db = db
        self._mem: dict[str, tuple[Any, datetime]] = {}

    def _load(self, key: str) -> tuple[Any, datetime] | None:
        if key in self._mem:
            return self._mem[key]
        row = self.db.query_one("SELECT data, fetched_at FROM intel_cache WHERE key = ?", (key,))
        if row is None:
            return None
        item = (json.loads(row["data"]), datetime.fromisoformat(row["fetched_at"]))
        self._mem[key] = item
        return item

    def get(self, key: str, max_age_s: float | None = None) -> Any | None:
        item = self._load(key)
        if item is None:
            return None
        data, fetched = item
        if max_age_s is not None and (_now() - fetched).total_seconds() > max_age_s:
            return None
        return data

    def set(self, key: str, data: Any) -> datetime:
        now = _now()
        self._mem[key] = (data, now)
        self.db.execute(
            "INSERT INTO intel_cache (key, data, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data = excluded.data, fetched_at = excluded.fetched_at",
            (key, json.dumps(data, ensure_ascii=False, default=str), now.isoformat(timespec="seconds")),
        )
        return now

    async def fetch(self, key: str, ttl_s: float, loader: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
        """Retorna {data, fetched_at, stale, error?} usando cache quando fresco."""
        item = self._load(key)
        if item is not None and (_now() - item[1]).total_seconds() <= ttl_s:
            return {"data": item[0], "fetched_at": item[1].isoformat(timespec="seconds"), "stale": False}
        try:
            data = await loader()
        except Exception as exc:  # noqa: BLE001 — qualquer falha de fonte cai no último dado bom
            if item is not None:
                return {
                    "data": item[0],
                    "fetched_at": item[1].isoformat(timespec="seconds"),
                    "stale": True,
                    "error": str(exc),
                }
            raise
        fetched = self.set(key, data)
        return {"data": data, "fetched_at": fetched.isoformat(timespec="seconds"), "stale": False}
