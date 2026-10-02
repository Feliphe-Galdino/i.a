"""Agendador: verifica alertas, mantém o cache aquecido e gera os resumos nos horários.

Simples de propósito (um laço a cada 30 s, sem bibliotecas extras). O estado de cada
tarefa fica no banco — reiniciar o PC não duplica resumos.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from ..memory.db import Database

log = logging.getLogger(__name__)

ALERTS_EVERY = timedelta(minutes=5)
PREFETCH_EVERY = timedelta(minutes=20)
BRIEFING_WINDOW = timedelta(hours=4)  # PC ligado até 4 h depois do horário ainda recebe o resumo


class Scheduler:
    def __init__(self, db: Database, runtime: Any, intel: Any, alerts: Any, briefings: Any):
        self.db = db
        self.runtime = runtime
        self.intel = intel
        self.alerts = alerts
        self.briefings = briefings
        self._task: asyncio.Task | None = None
        self._busy: set[str] = set()

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task is None:
            self._task = loop.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(10)  # deixa o servidor terminar de subir
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Falha no agendador")
            await asyncio.sleep(30)

    # --- Estado ---------------------------------------------------------------------
    def last_run(self, job: str) -> datetime | None:
        row = self.db.query_one("SELECT last_run FROM scheduler_state WHERE job = ?", (job,))
        return datetime.fromisoformat(row["last_run"]) if row and row["last_run"] else None

    def mark(self, job: str, when: datetime) -> None:
        self.db.execute(
            "INSERT INTO scheduler_state (job, last_run) VALUES (?, ?) ON CONFLICT(job) DO UPDATE SET last_run = excluded.last_run",
            (job, when.isoformat(timespec="seconds")),
        )

    def _due(self, job: str, every: timedelta, now: datetime) -> bool:
        last = self.last_run(job)
        return last is None or now - last >= every

    # --- Execução ---------------------------------------------------------------------
    async def tick(self, now: datetime | None = None) -> list[str]:
        """Executa o que estiver vencido. Retorna os nomes das tarefas executadas."""
        now = now or datetime.now().astimezone()
        cfg = self.runtime.get()
        if not cfg.intel_enabled:
            return []
        ran: list[str] = []
        if self._due("alerts", ALERTS_EVERY, now):
            self.mark("alerts", now)
            await self.alerts.evaluate(self.intel)
            ran.append("alerts")
        if self._due("prefetch", PREFETCH_EVERY, now):
            self.mark("prefetch", now)
            await self.intel.overview()
            ran.append("prefetch")
        if cfg.briefing_enabled:
            for hhmm in cfg.briefing_times:
                hour, minute = (int(x) for x in hhmm.split(":"))
                slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                job = f"briefing:{slot.date().isoformat()}:{hhmm}"
                if slot <= now < slot + BRIEFING_WINDOW and self.last_run(job) is None and job not in self._busy:
                    self._busy.add(job)
                    try:
                        self.mark(job, now)
                        await self.briefings.generate("diário")
                        ran.append(job)
                    finally:
                        self._busy.discard(job)
        return ran
