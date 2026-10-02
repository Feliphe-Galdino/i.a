"""Rotas de informações (tela "Mundo"), alertas e resumos."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..container import Sexta
from ..intel.alerts import KINDS
from ..intel.feeds import CATEGORY_LABELS
from ..intel.http import FetchError
from .deps import get_sexta, require_token

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(502, f"Fonte indisponível: {exc}")


@router.get("/intel/overview")
async def overview(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    data = await sexta.intel.overview()
    data["categories"] = CATEGORY_LABELS
    data["alert_events"] = sexta.alerts.events(8)
    data["briefing"] = sexta.briefings.latest()
    data["city"] = sexta.runtime.get().city
    return data


@router.get("/intel/news")
async def news(
    category: str = "brasil",
    q: str | None = None,
    limit: int = Query(15, ge=1, le=40),
    sexta: Sexta = Depends(get_sexta),
) -> dict[str, Any]:
    try:
        return await (sexta.intel.news_search(q, limit) if q else sexta.intel.news(category, limit))
    except FetchError as exc:
        raise _fail(exc) from exc


@router.get("/intel/weather")
async def weather(city: str | None = None, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    try:
        return await sexta.intel.weather(city)
    except FetchError as exc:
        raise _fail(exc) from exc


@router.get("/intel/quotes")
async def quotes(symbols: str = "", sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    wanted = [s for s in symbols.split(",") if s.strip()] or None
    try:
        return await sexta.intel.quotes(wanted)
    except FetchError as exc:
        raise _fail(exc) from exc


@router.get("/intel/history")
async def history(symbol: str, period: str = "1mo", sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    try:
        return await sexta.intel.history(symbol, period)
    except FetchError as exc:
        raise _fail(exc) from exc


@router.get("/intel/histories")
async def histories(symbols: str = "", period: str = "1mo", sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    """Históricos curtos para as minilinhas (sparklines) da lista de acompanhamento."""
    wanted = [s for s in symbols.split(",") if s.strip()] or sexta.runtime.get().watchlist
    results = await asyncio.gather(*(sexta.intel.history(s, period) for s in wanted[:20]), return_exceptions=True)
    return {
        s: ({"closes": r["closes"], "dates": r["dates"]} if not isinstance(r, Exception) else {"error": str(r)})
        for s, r in zip(wanted, results, strict=False)
    }


@router.get("/intel/indicators")
async def indicators(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    try:
        return await sexta.intel.indicators()
    except FetchError as exc:
        raise _fail(exc) from exc


# --- Alertas ---------------------------------------------------------------------------


class AlertIn(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    cooldown_h: float = Field(default=6, ge=0.1, le=168)


class AlertPatch(BaseModel):
    enabled: bool


@router.get("/alerts")
def list_alerts(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    return {"alerts": sexta.alerts.list(), "events": sexta.alerts.events(30), "kinds": KINDS}


@router.post("/alerts")
def create_alert(body: AlertIn, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    try:
        alert = sexta.alerts.create(body.kind, body.params, label=body.label, cooldown_h=body.cooldown_h)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, f"Alerta inválido: {exc}") from exc
    sexta.audit.record("alert_created", detail={"id": alert["id"], "label": alert["label"]})
    return alert


@router.patch("/alerts/{alert_id}")
def patch_alert(alert_id: int, body: AlertPatch, sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    alert = sexta.alerts.set_enabled(alert_id, body.enabled)
    if alert is None:
        raise HTTPException(404, "Alerta não encontrado.")
    return alert


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, sexta: Sexta = Depends(get_sexta)) -> dict[str, str]:
    if not sexta.alerts.delete(alert_id):
        raise HTTPException(404, "Alerta não encontrado.")
    sexta.audit.record("alert_deleted", detail={"id": alert_id})
    return {"status": "ok"}


@router.post("/alerts/check")
async def check_alerts(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    return {"triggered": await sexta.alerts.evaluate(sexta.intel)}


# --- Resumos ---------------------------------------------------------------------------


@router.get("/briefings")
def list_briefings(limit: int = Query(10, ge=1, le=50), sexta: Sexta = Depends(get_sexta)) -> list[dict[str, Any]]:
    return sexta.briefings.list(limit)


@router.post("/briefings")
async def generate_briefing(sexta: Sexta = Depends(get_sexta)) -> dict[str, Any]:
    asyncio.get_running_loop().create_task(sexta.briefings.generate("sob demanda"))
    return {"started": True}
