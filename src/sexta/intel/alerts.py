"""Alertas personalizados.

Tipos:
* ``preco_acima`` / ``preco_abaixo`` — {symbol, value}: cotação cruzou um valor;
* ``variacao`` — {symbol, pct}: variação diária (em módulo) maior que X%;
* ``noticia`` — {keywords, categories?}: notícia nova com alguma palavra-chave;
* ``clima`` — {rain_mm?, temp_max?, temp_min?, wind_kmh?}: previsão para hoje/amanhã.

Cada alerta tem tempo de espera (``cooldown_h``) para não repetir; alertas de preço
desligam sozinhos depois de disparar (``once``), a menos que você mude isso.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ..memory.db import Database, utcnow
from ..memory.text import normalize
from . import feeds, weather

log = logging.getLogger(__name__)

KINDS = {
    "preco_acima": "Preço acima de",
    "preco_abaixo": "Preço abaixo de",
    "variacao": "Variação diária maior que",
    "noticia": "Notícia com palavra-chave",
    "clima": "Aviso de clima",
}


def _validate(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"tipo de alerta desconhecido: {kind}")
    clean: dict[str, Any] = {}
    if kind in ("preco_acima", "preco_abaixo", "variacao"):
        symbol = str(params.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("informe o ativo (ex.: PETR4, BTC, USD, IBOV)")
        clean["symbol"] = symbol
        if kind == "variacao":
            clean["pct"] = abs(float(params.get("pct") or 0)) or 3.0
        else:
            if params.get("value") in (None, ""):
                raise ValueError("informe o valor de referência")
            clean["value"] = float(params["value"])
    elif kind == "noticia":
        raw = params.get("keywords") or ""
        words = raw if isinstance(raw, list) else str(raw).split(",")
        keywords = [w.strip() for w in words if w.strip()][:10]
        if not keywords:
            raise ValueError("informe ao menos uma palavra-chave")
        clean["keywords"] = keywords
        categories = [c for c in (params.get("categories") or []) if c in feeds.FEEDS]
        clean["categories"] = categories or list(feeds.FEEDS)
    else:
        for key in ("rain_mm", "temp_max", "temp_min", "wind_kmh"):
            if params.get(key) not in (None, ""):
                clean[key] = float(params[key])
        if not clean:
            clean = dict(weather.DEFAULT_THRESHOLDS)
    clean["once"] = bool(params.get("once", kind in ("preco_acima", "preco_abaixo")))
    return clean


CLIMATE_LIMITS = {
    "rain_mm": ("chuva ≥", "mm"),
    "temp_max": ("máxima ≥", "°C"),
    "temp_min": ("mínima ≤", "°C"),
    "wind_kmh": ("vento ≥", "km/h"),
}


def _num(value: float) -> str:
    """Número no formato brasileiro, sem casas desnecessárias (5.3 → "5,3")."""
    return f"{value:g}".replace(".", ",")


def describe_alert(kind: str, params: dict[str, Any]) -> str:
    if kind == "preco_acima":
        return f"{params['symbol']} acima de {_num(params['value'])}"
    if kind == "preco_abaixo":
        return f"{params['symbol']} abaixo de {_num(params['value'])}"
    if kind == "variacao":
        return f"{params['symbol']} variando mais de {_num(params['pct'])}% no dia"
    if kind == "noticia":
        return f"Notícias sobre: {', '.join(params['keywords'])}"
    limits = [
        f"{CLIMATE_LIMITS[k][0]} {_num(v)} {CLIMATE_LIMITS[k][1]}" for k, v in params.items() if k in CLIMATE_LIMITS
    ]
    return "Clima: " + ", ".join(limits)


class AlertService:
    def __init__(self, db: Database, bus: Any):
        self.db = db
        self.bus = bus

    # --- CRUD -----------------------------------------------------------------------
    def create(self, kind: str, params: dict[str, Any], *, label: str = "", cooldown_h: float = 6.0) -> dict:
        clean = _validate(kind, params)
        cur = self.db.execute(
            "INSERT INTO alerts (kind, params, label, cooldown_h, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                kind,
                json.dumps(clean, ensure_ascii=False),
                label.strip()[:120] or describe_alert(kind, clean),
                max(0.1, float(cooldown_h)),
                utcnow(),
            ),
        )
        return self.get(int(cur.lastrowid))

    def get(self, alert_id: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM alerts WHERE id = ?", (alert_id,))
        return self._row(row) if row else None

    def list(self) -> list[dict]:
        return [self._row(r) for r in self.db.query("SELECT * FROM alerts ORDER BY id DESC")]

    def set_enabled(self, alert_id: int, enabled: bool) -> dict | None:
        self.db.execute("UPDATE alerts SET enabled = ? WHERE id = ?", (int(enabled), alert_id))
        return self.get(alert_id)

    def delete(self, alert_id: int) -> bool:
        return self.db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,)).rowcount > 0

    def events(self, limit: int = 30) -> list[dict]:
        rows = self.db.query("SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["data"] = json.loads(row["data"] or "{}")
        return rows

    @staticmethod
    def _row(row: dict) -> dict:
        row = dict(row)
        row["params"] = json.loads(row["params"] or "{}")
        row["enabled"] = bool(row["enabled"])
        row["kind_label"] = KINDS.get(row["kind"], row["kind"])
        return row

    # --- Avaliação --------------------------------------------------------------------
    async def evaluate(self, intel: Any, *, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(UTC)
        triggered: list[dict] = []
        alerts = [a for a in self.list() if a["enabled"]]
        if not alerts:
            return []
        quote_cache: dict[str, Any] = {}
        for alert in alerts:
            if alert["last_triggered_at"]:
                last = datetime.fromisoformat(alert["last_triggered_at"])
                if now - last < timedelta(hours=alert["cooldown_h"]):
                    continue
            try:
                hit = await self._check(alert, intel, quote_cache)
            except Exception as exc:  # noqa: BLE001 — fonte fora do ar não derruba os outros alertas
                log.info("Alerta %s não avaliado: %s", alert["id"], exc)
                continue
            if hit:
                triggered.append(await self._trigger(alert, *hit, now=now))
        return triggered

    async def _quote(self, intel: Any, symbol: str, cache: dict[str, Any]) -> dict | None:
        if symbol not in cache:
            data = await intel.quotes([symbol])
            cache[symbol] = data["quotes"][0] if data.get("quotes") else None
        return cache[symbol]

    async def _check(self, alert: dict, intel: Any, cache: dict[str, Any]) -> tuple[str, str, dict] | None:
        kind, p = alert["kind"], alert["params"]
        if kind in ("preco_acima", "preco_abaixo", "variacao"):
            quote = await self._quote(intel, p["symbol"], cache)
            if not quote:
                return None
            price, change = quote["price"], quote.get("change_pct")
            when = f"(fonte: {quote['source']}, {quote.get('time') or 'agora'})"
            if kind == "preco_acima" and price >= p["value"]:
                return (f"{quote['label']} acima de {p['value']:g}", f"Cotação atual: {price:,.2f} {when}", quote)
            if kind == "preco_abaixo" and price <= p["value"]:
                return (f"{quote['label']} abaixo de {p['value']:g}", f"Cotação atual: {price:,.2f} {when}", quote)
            if kind == "variacao" and change is not None and abs(change) >= p["pct"]:
                direction = "sobe" if change > 0 else "cai"
                return (f"{quote['label']} {direction} {abs(change):.2f}% hoje", f"Cotação: {price:,.2f} {when}", quote)
            return None
        if kind == "noticia":
            keywords = [normalize(k) for k in p["keywords"]]
            seen_key = f"alert_seen:{alert['id']}"
            seen = set(intel.cache.get(seen_key) or [])
            first_run = not seen
            matches = []
            for category in p["categories"]:
                news = await intel.news(category, 30)
                for item in news["items"]:
                    if item["guid"] in seen:
                        continue
                    seen.add(item["guid"])
                    haystack = normalize(f"{item['title']} {item.get('summary', '')}")
                    if any(k and k in haystack for k in keywords):
                        matches.append(item)
            intel.cache.set(seen_key, list(seen)[-3000:])
            if first_run or not matches:  # 1ª execução só memoriza o que já existia
                return None
            headlines = "; ".join(f"{m['title']} ({m['source']})" for m in matches[:3])
            return (f"Notícia sobre {', '.join(p['keywords'])}", headlines, {"items": matches[:5]})
        if kind == "clima":
            forecast = await intel.weather()
            thresholds = {k: v for k, v in p.items() if k != "once"}
            risks = weather.weather_risks(forecast["daily"], thresholds)
            if risks:
                return (
                    f"Clima em {forecast['place']['name']}",
                    "; ".join(risks) + f" (fonte: {weather.SOURCE})",
                    {"risks": risks},
                )
            return None
        return None

    async def _trigger(self, alert: dict, title: str, message: str, data: dict, *, now: datetime) -> dict:
        ts = now.isoformat(timespec="seconds")
        cur = self.db.execute(
            "INSERT INTO alert_events (alert_id, ts, title, message, data) VALUES (?, ?, ?, ?, ?)",
            (alert["id"], ts, title, message, json.dumps(data, ensure_ascii=False, default=str)),
        )
        self.db.execute("UPDATE alerts SET last_triggered_at = ? WHERE id = ?", (ts, alert["id"]))
        if alert["params"].get("once"):
            self.db.execute("UPDATE alerts SET enabled = 0 WHERE id = ?", (alert["id"],))
        event = {
            "type": "alert",
            "event_id": int(cur.lastrowid),
            "alert_id": alert["id"],
            "title": title,
            "message": message,
        }
        await self.bus.publish(event)
        return event
