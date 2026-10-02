"""Serviço de informações: notícias, tendências, clima, mercado e indicadores.

Fachada única usada pelas ferramentas da IA, pela API (tela "Mundo"), pelos alertas e
pelos resumos. Todas as respostas trazem fonte e horário de atualização.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..memory.db import Database
from . import feeds, market, weather
from .cache import IntelCache
from .http import FetchError, HttpClient

log = logging.getLogger(__name__)

TTL = {
    "news": 15 * 60,
    "search": 10 * 60,
    "trends": 30 * 60,
    "weather": 30 * 60,
    "geocode": 30 * 24 * 3600,
    "quotes": 2 * 60,
    "history": 30 * 60,
    "indicators": 6 * 3600,
}


class IntelService:
    def __init__(self, db: Database, runtime: Any, http: HttpClient | None = None):
        self.runtime = runtime
        self.cache = IntelCache(db)
        self.http = http or HttpClient()

    # --- Notícias -------------------------------------------------------------------
    async def news(self, category: str = "brasil", limit: int = 10) -> dict[str, Any]:
        category = category if category in feeds.FEEDS else "brasil"

        async def load_feed(source: str, url: str) -> list[dict]:
            text = await self.http.text(url)
            return [i.to_dict() for i in feeds.parse_feed(text, source=source, category=category)]

        groups, errors, fetched = [], [], []
        results = await asyncio.gather(
            *(
                self.cache.fetch(f"feed:{u}", TTL["news"], lambda s=s, u=u: load_feed(s, u))
                for s, u in feeds.FEEDS[category]
            ),
            return_exceptions=True,
        )
        for (source, _url), result in zip(feeds.FEEDS[category], results, strict=True):
            if isinstance(result, Exception):
                errors.append(f"{source}: {result}")
                continue
            groups.append([feeds.FeedItem(**item) for item in result["data"]])
            fetched.append(result["fetched_at"])
            if result.get("stale"):
                errors.append(f"{source}: usando dados de {result['fetched_at']} ({result.get('error')})")
        items = feeds.merge_items(groups, limit)
        return {
            "category": category,
            "label": feeds.CATEGORY_LABELS.get(category, category),
            "items": [i.to_dict() for i in items],
            "sources": [s for s, _ in feeds.FEEDS[category]],
            "fetched_at": max(fetched) if fetched else None,
            "errors": errors,
        }

    async def news_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        query = " ".join(query.split())[:120]
        url = feeds.google_news_url(query)

        async def load() -> list[dict]:
            text = await self.http.text(url)
            return [i.to_dict() for i in feeds.parse_feed(text, source="Google Notícias", category="busca")]

        result = await self.cache.fetch(f"search:{query.lower()}", TTL["search"], load)
        items = feeds.merge_items([[feeds.FeedItem(**i) for i in result["data"]]], limit)
        return {
            "query": query,
            "items": [i.to_dict() for i in items],
            "fetched_at": result["fetched_at"],
            "source": "Google Notícias",
        }

    async def trends(self, limit: int = 15) -> dict[str, Any]:
        async def load() -> list[dict]:
            text = await self.http.text(feeds.TRENDS_URL)
            return [i.to_dict() for i in feeds.parse_feed(text, source="Google Trends", category="tendencias")]

        result = await self.cache.fetch("trends:BR", TTL["trends"], load)
        return {
            "items": result["data"][:limit],
            "fetched_at": result["fetched_at"],
            "source": "Google Trends (Brasil)",
        }

    # --- Clima ------------------------------------------------------------------------
    async def weather(self, city: str | None = None, days: int = 7) -> dict[str, Any]:
        city = (city or self.runtime.get().city or "").strip()
        if not city:
            raise FetchError("Nenhuma cidade configurada. Defina sua cidade em Configurações → Informações.")
        place = (
            await self.cache.fetch(f"geo:{city.lower()}", TTL["geocode"], lambda: weather.geocode(self.http, city))
        )["data"]
        result = await self.cache.fetch(
            f"weather:{place['lat']:.2f},{place['lon']:.2f}",
            TTL["weather"],
            lambda: weather.forecast(self.http, place["lat"], place["lon"], 7),
        )
        data = dict(result["data"])
        data["daily"] = data["daily"][:days]
        return {
            "place": place,
            **data,
            "risks": weather.weather_risks(result["data"]["daily"]),
            "fetched_at": result["fetched_at"],
            "stale": result["stale"],
        }

    # --- Mercado ----------------------------------------------------------------------
    async def quotes(self, symbols: list[str] | None = None) -> dict[str, Any]:
        symbols = [s for s in (symbols or self.runtime.get().watchlist) if s.strip()][:20]
        key = "quotes:" + ",".join(sorted(s.lower() for s in symbols))
        result = await self.cache.fetch(key, TTL["quotes"], lambda: market.quotes(self.http, symbols))
        return {**result["data"], "fetched_at": result["fetched_at"], "stale": result["stale"]}

    async def history(self, symbol: str, period: str = "3mo") -> dict[str, Any]:
        key = f"history:{symbol.lower()}:{period}"
        result = await self.cache.fetch(key, TTL["history"], lambda: market.history(self.http, symbol, period))
        return {**result["data"], "fetched_at": result["fetched_at"], "stale": result["stale"]}

    async def indicators(self) -> dict[str, Any]:
        result = await self.cache.fetch("indicators:bcb", TTL["indicators"], lambda: market.indicators(self.http))
        return {"items": result["data"], "fetched_at": result["fetched_at"], "stale": result["stale"]}

    # --- Visão geral ------------------------------------------------------------------
    async def overview(self, *, news_limit: int = 5) -> dict[str, Any]:
        """Tudo de uma vez (painel "Mundo" e resumos). Cada parte falha de forma isolada."""
        cfg = self.runtime.get()

        async def safe(coro):
            try:
                return await coro
            except Exception as exc:  # noqa: BLE001
                return {"error": str(exc)}

        topics = [t for t in cfg.news_topics if t in feeds.FEEDS] or ["brasil"]
        tasks = {
            "weather": safe(self.weather()) if cfg.city else None,
            "quotes": safe(self.quotes()),
            "indicators": safe(self.indicators()),
            "trends": safe(self.trends(10)),
            **{f"news:{t}": safe(self.news(t, news_limit)) for t in topics},
        }
        keys = [k for k, v in tasks.items() if v is not None]
        values = await asyncio.gather(*(tasks[k] for k in keys))
        result: dict[str, Any] = {"news": {}, "weather": None}
        for key, value in zip(keys, values, strict=True):
            if key.startswith("news:"):
                result["news"][key[5:]] = value
            else:
                result[key] = value
        return result
