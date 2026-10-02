"""Fase 3a: notícias, tendências, clima, mercado, alertas, resumos e agendador (HTTP simulado)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import TOKEN, ScriptedProvider, collect_until_done, text, tool_use
from sexta.app import create_app
from sexta.container import build_sexta
from sexta.intel import feeds
from sexta.intel.http import HttpClient
from sexta.intel.market import compute_stats, resolve_symbol
from sexta.intel.weather import weather_risks

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>G1</title>
<item><title>Governo anuncia &lt;b&gt;novo&lt;/b&gt; programa</title><link>https://g1.globo.com/a</link>
<description><![CDATA[<p>Medida vale a partir de <b>janeiro</b>.</p>]]></description>
<pubDate>Thu, 01 Oct 2026 10:00:00 -0300</pubDate><guid>a1</guid></item>
<item><title>Inteligência artificial chega às escolas</title><link>https://g1.globo.com/b</link>
<pubDate>Thu, 01 Oct 2026 12:00:00 -0300</pubDate></item>
</channel></rss>"""

RSS_AGENCIA = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Inteligência artificial chega às escolas</title><link>https://agencia/x</link>
<pubDate>Thu, 01 Oct 2026 11:00:00 -0300</pubDate></item>
<item><title>Chuvas atingem o Sul</title><link>https://agencia/y</link>
<pubDate>Thu, 01 Oct 2026 09:00:00 -0300</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>The Verge</title>
<entry><title>New chip announced</title><link rel="alternate" href="https://verge.com/chip"/>
<id>tag:verge,1</id><updated>2026-10-01T15:00:00Z</updated><summary>Fast &amp; small</summary></entry>
</feed>"""

TRENDS = """<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>eleições</title><ht:approx_traffic>200 mil+</ht:approx_traffic><pubDate>Thu, 01 Oct 2026 08:00:00 -0700</pubDate></item>
<item><title>final do campeonato</title><ht:approx_traffic>50 mil+</ht:approx_traffic></item>
</channel></rss>"""

GEOCODE = {
    "results": [
        {
            "name": "São Paulo",
            "admin1": "São Paulo",
            "country": "Brasil",
            "latitude": -23.55,
            "longitude": -46.63,
            "timezone": "America/Sao_Paulo",
        }
    ]
}
FORECAST = {
    "timezone": "America/Sao_Paulo",
    "current": {
        "time": "2026-10-01T15:00",
        "temperature_2m": 27.4,
        "apparent_temperature": 28.0,
        "relative_humidity_2m": 60,
        "precipitation": 0,
        "weather_code": 2,
        "wind_speed_10m": 12,
    },
    "daily": {
        "time": ["2026-10-01", "2026-10-02", "2026-10-03"],
        "temperature_2m_max": [29, 36, 25],
        "temperature_2m_min": [18, 20, 16],
        "precipitation_sum": [0, 42, 2],
        "precipitation_probability_max": [10, 90, 30],
        "wind_speed_10m_max": [20, 35, 15],
        "uv_index_max": [8, 6, 5],
        "weather_code": [2, 95, 3],
    },
}
AWESOME = {"USDBRL": {"bid": "5.4321", "pctChange": "0.85", "timestamp": "1790000000"}}
COINGECKO = {"bitcoin": {"brl": 350000.0, "usd": 64000, "brl_24h_change": -2.5, "last_updated_at": 1790000000}}


def yahoo(price: float, previous: float, name: str, currency: str = "BRL", closes: list | None = None) -> dict:
    closes = closes or [previous, price]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "chartPreviousClose": previous,
                        "shortName": name,
                        "currency": currency,
                        "regularMarketTime": 1790000000,
                    },
                    "timestamp": [1790000000 + 86400 * i for i in range(len(closes))],
                    "indicators": {"quote": [{"close": closes}]},
                }
            ],
            "error": None,
        }
    }


BCB = {
    432: [{"data": "18/09/2026", "valor": "10.75"}, {"data": "01/10/2026", "valor": "10.50"}],
    13522: [{"data": "01/08/2026", "valor": "4.10"}, {"data": "01/09/2026", "valor": "4.02"}],
}


class FakeWeb:
    """Servidor HTTP simulado para todas as fontes."""

    def __init__(self):
        self.calls: list[str] = []
        self.down: set[str] = set()
        self.rss = {"g1.globo.com": RSS, "agenciabrasil.ebc.com.br": RSS_AGENCIA}
        self.prices = {"^BVSP": (130000.0, 128700.0, "IBOVESPA"), "PETR4.SA": (38.5, 37.9, "PETROBRAS PN")}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.calls.append(f"{host}{path}")
        if host in self.down:
            raise httpx.ConnectError("offline", request=request)
        if host in self.rss:
            return httpx.Response(200, text=self.rss[host])
        if host == "www.theverge.com":
            return httpx.Response(200, text=ATOM)
        if host == "trends.google.com":
            return httpx.Response(200, text=TRENDS)
        if host == "news.google.com":
            return httpx.Response(200, text=RSS)
        if host == "geocoding-api.open-meteo.com":
            return httpx.Response(200, json=GEOCODE)
        if host == "api.open-meteo.com":
            return httpx.Response(200, json=FORECAST)
        if host == "economia.awesomeapi.com.br":
            return httpx.Response(200, json=AWESOME)
        if host == "api.coingecko.com":
            return httpx.Response(200, json=COINGECKO)
        if host == "query1.finance.yahoo.com":
            code = path.rsplit("/", 1)[-1]
            if code not in self.prices:
                return httpx.Response(404, json={"chart": {"result": None, "error": {"description": "No data found"}}})
            price, prev, name = self.prices[code]
            return httpx.Response(200, json=yahoo(price, prev, name, closes=[prev * 0.98, prev, price]))
        if host == "api.bcb.gov.br":
            code = int(path.split("bcdata.sgs.")[1].split("/")[0])
            return httpx.Response(200, json=BCB.get(code, [{"data": "01/10/2026", "valor": "1.0"}]))
        return httpx.Response(404, text="not found")


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def sx(settings, web):
    provider = ScriptedProvider()
    instance = build_sexta(settings, provider=provider, http=HttpClient(transport=httpx.MockTransport(web)))
    instance.runtime.update(
        {"city": "São Paulo", "watchlist": ["IBOV", "USD", "BTC", "PETR4"], "news_topics": ["brasil"]}
    )
    instance.provider_for_tests = provider
    yield instance
    instance.close()


# --- Parsers e funções puras ---------------------------------------------------------


def test_yahoo_daily_change_uses_previous_session_not_chart_start():
    from sexta.intel.market import _previous_close

    day = 86400
    result = yahoo(121.0, 90.0, "X", closes=[100.0, 110.0, 121.0])["chart"]["result"][0]
    result["meta"]["regularMarketTime"] = result["timestamp"][-1] + 3600  # pregão de hoje em andamento
    assert _previous_close(result) == 110.0  # ontem, e não o início do gráfico (90)
    # Fechamento de hoje ainda vazio: continua sendo o último pregão anterior
    result["indicators"]["quote"][0]["close"] = [100.0, 110.0, None]
    assert _previous_close(result) == 110.0
    # Sem barras anteriores: usa o que a fonte informar
    result["meta"]["regularMarketTime"] = result["timestamp"][0] - day
    assert _previous_close(result) == 90.0


def test_parse_rss_atom_and_trends():
    items = feeds.parse_feed(RSS, source="G1", category="brasil")
    assert items[0].title == "Governo anuncia novo programa"
    assert items[0].summary == "Medida vale a partir de janeiro ."
    assert items[0].published == "2026-10-01T13:00:00+00:00"
    atom = feeds.parse_feed(ATOM, source="The Verge", category="tecnologia")
    assert atom[0].link == "https://verge.com/chip" and atom[0].summary == "Fast & small"
    trends = feeds.parse_feed(TRENDS, source="Google Trends", category="tendencias")
    assert trends[0].traffic == "200 mil+"


def test_xml_bomb_is_rejected():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><channel><item><title>&b;</title></item></channel></rss>'
    with pytest.raises(Exception):  # noqa: B017 — defusedxml recusa entidades
        feeds.parse_feed(bomb, source="x", category="y")


def test_merge_dedupes_and_sorts():
    g1 = feeds.parse_feed(RSS, source="G1", category="brasil")
    ag = feeds.parse_feed(RSS_AGENCIA, source="Agência", category="brasil")
    merged = feeds.merge_items([g1, ag], 10)
    titles = [i.title for i in merged]
    assert titles.count("Inteligência artificial chega às escolas") == 1
    assert titles[0] == "Inteligência artificial chega às escolas"  # mais recente primeiro


def test_symbols_and_stats():
    assert resolve_symbol("PETR4") == ("yahoo", "PETR4.SA", "PETR4")
    assert resolve_symbol("dólar") == ("awesome", "USD-BRL", "Dólar")
    assert resolve_symbol("btc")[0] == "coingecko"
    assert resolve_symbol("AAPL") == ("yahoo", "AAPL", "AAPL")
    stats = compute_stats([100, 110, 99, 120])
    assert stats["change_period_pct"] == 20.0
    assert stats["max_drawdown_pct"] == -10.0
    assert stats["max"] == 120 and stats["min"] == 99
    assert "não são previsões" in stats["note"]


def test_weather_risks():
    daily = [{"date": "d1", "rain_mm": 45, "tmax": 30, "tmin": 18, "wind_max": 10, "code": 95}]
    risks = weather_risks(daily)
    assert any("Chuva forte" in r for r in risks) and any("tempestade" in r for r in risks)


# --- Serviço ----------------------------------------------------------------------------


async def test_news_merges_caches_and_reports_failures(sx, web):
    data = await sx.intel.news("brasil", 10)
    assert len(data["items"]) == 3 and data["errors"] == []
    calls = len(web.calls)
    await sx.intel.news("brasil", 10)
    assert len(web.calls) == calls  # veio do cache
    web.down.add("agenciabrasil.ebc.com.br")
    sx.intel.cache._mem.clear()  # noqa: SLF001
    sx.db.execute("UPDATE intel_cache SET fetched_at = '2000-01-01T00:00:00+00:00'")
    data = await sx.intel.news("brasil", 10)
    assert any("usando dados de" in e for e in data["errors"])  # fonte fora do ar: último dado bom
    assert len(data["items"]) == 3


async def test_weather_quotes_history_indicators(sx, web):
    weather = await sx.intel.weather()
    assert weather["place"]["name"] == "São Paulo"
    assert weather["current"]["desc"] == "parcialmente nublado"
    assert any("Chuva forte prevista amanhã" in r for r in weather["risks"])
    quotes = await sx.intel.quotes()
    by_symbol = {q["symbol"]: q for q in quotes["quotes"]}
    assert set(by_symbol) == {"IBOV", "USD", "BTC", "PETR4"}
    assert by_symbol["USD"]["price"] == 5.4321 and "AwesomeAPI" in by_symbol["USD"]["source"]
    assert by_symbol["PETR4"]["change_pct"] == round((38.5 / 37.9 - 1) * 100, 2)
    assert by_symbol["BTC"]["change_pct"] == -2.5
    bad = await sx.intel.quotes(["XXXX9"])
    assert bad["quotes"] == [] and bad["errors"]
    history = await sx.intel.history("PETR4", "1mo")
    assert history["stats"]["last"] == 38.5 and len(history["closes"]) == 3
    indicators = await sx.intel.indicators()
    selic = next(i for i in indicators["items"] if i["code"] == 432)
    assert selic["value"] == 10.5 and selic["previous"] == 10.75 and "oficial" in selic["source"]


async def test_weather_without_city_explains(sx):
    sx.runtime.update({"city": ""})
    with pytest.raises(Exception, match="Nenhuma cidade"):
        await sx.intel.weather()


# --- Alertas ------------------------------------------------------------------------------


async def test_alert_validation_and_price_alert_triggers_once(sx):
    with pytest.raises(ValueError):
        sx.alerts.create("preco_acima", {"symbol": "PETR4"})
    with pytest.raises(ValueError):
        sx.alerts.create("desconhecido", {})
    alert = sx.alerts.create("preco_acima", {"symbol": "PETR4", "value": 38})
    assert alert["label"] == "PETR4 acima de 38" and alert["params"]["once"] is True
    queue = sx.bus.subscribe()
    fired = await sx.alerts.evaluate(sx.intel)
    assert len(fired) == 1 and "acima de 38" in fired[0]["title"]
    assert queue.get_nowait()["type"] == "alert"
    assert sx.alerts.get(alert["id"])["enabled"] is False  # desliga depois de disparar
    assert await sx.alerts.evaluate(sx.intel) == []


def test_alert_labels_are_readable(sx):
    assert sx.alerts.create("preco_abaixo", {"symbol": "USD", "value": 5.3})["label"] == "USD abaixo de 5,3"
    climate = sx.alerts.create("clima", {"rain_mm": 30, "temp_min": 5})
    assert climate["label"] == "Clima: chuva ≥ 30 mm, mínima ≤ 5 °C"


async def test_variation_cooldown_and_weather_alert(sx):
    sx.alerts.create("variacao", {"symbol": "BTC", "pct": 2})
    sx.alerts.create("clima", {"rain_mm": 30})
    now = datetime.now().astimezone()
    fired = await sx.alerts.evaluate(sx.intel, now=now)
    titles = sorted(f["title"] for f in fired)
    assert any("Bitcoin cai 2.50% hoje" in t for t in titles)
    assert any("Clima em São Paulo" in t for t in titles)
    assert await sx.alerts.evaluate(sx.intel, now=now + timedelta(hours=1)) == []  # em espera
    assert len(await sx.alerts.evaluate(sx.intel, now=now + timedelta(hours=7))) == 2


async def test_news_keyword_alert_only_fires_on_new_items(sx, web):
    sx.alerts.create("noticia", {"keywords": "chuva, enchente", "categories": ["brasil"]})
    assert await sx.alerts.evaluate(sx.intel) == []  # 1ª vez só memoriza
    web.rss["agenciabrasil.ebc.com.br"] = RSS_AGENCIA.replace(
        "</channel>",
        "<item><title>Chuva forte causa enchente em Porto Alegre</title><link>https://agencia/z</link>"
        "<pubDate>Thu, 01 Oct 2026 18:00:00 -0300</pubDate></item></channel>",
    )
    sx.intel.cache._mem.clear()  # noqa: SLF001
    sx.db.execute("UPDATE intel_cache SET fetched_at = '2000-01-01T00:00:00+00:00' WHERE key LIKE 'feed:%'")
    fired = await sx.alerts.evaluate(sx.intel)
    assert len(fired) == 1 and "enchente" in fired[0]["message"]


# --- Resumos e agendador ----------------------------------------------------------------


async def test_briefing_offline_template(settings, web):
    from sexta.llm.offline import OfflineProvider

    instance = build_sexta(settings, provider=OfflineProvider(), http=HttpClient(transport=httpx.MockTransport(web)))
    try:
        instance.runtime.update({"city": "São Paulo", "watchlist": ["USD"], "news_topics": ["brasil"]})
        briefing = await instance.briefings.generate()
        assert "**Clima — São Paulo" in briefing["text"]
        assert "Dólar" in briefing["text"] and "Governo anuncia novo programa" in briefing["text"]
        assert instance.briefings.latest()["id"] == briefing["id"]
    finally:
        instance.close()


async def test_briefing_with_ai_uses_conversation(sx):
    sx.provider_for_tests.add([text("Dia tranquilo com chuva amanhã.\n\nDetalhes...")])
    briefing = await sx.briefings.generate()
    assert briefing["headline"] == "Dia tranquilo com chuva amanhã."
    prompt = sx.provider_for_tests.requests[0].messages[-1]["content"][1]["text"]
    assert "DADOS:" in prompt and "São Paulo" in prompt
    assert sx.provider_for_tests.requests[0].model == "claude-sonnet-5-5"  # modo equilibrado


async def test_scheduler_runs_jobs_and_briefing_once(sx):
    sx.runtime.update({"briefing_times": ["08:00"]})
    sx.provider_for_tests.add([text("Resumo das 8h.")])
    morning = datetime.now().astimezone().replace(hour=8, minute=5, second=0, microsecond=0)
    ran = await sx.scheduler.tick(morning)
    assert "alerts" in ran and "prefetch" in ran and any(r.startswith("briefing:") for r in ran)
    ran_again = await sx.scheduler.tick(morning + timedelta(minutes=1))
    assert not any(r.startswith("briefing:") for r in ran_again)
    evening = morning.replace(hour=20)
    assert not any(r.startswith("briefing:") for r in await sx.scheduler.tick(evening))  # fora da janela


# --- Ferramentas da IA e API ---------------------------------------------------------------


async def test_ai_tool_market_quotes_includes_sources(sx):
    provider = sx.provider_for_tests
    provider.add([tool_use("t1", "market_quotes", {"symbols": ["USD", "PETR4"]})], stop_reason="tool_use").add(
        [text("Dólar a R$ 5,43.")]
    )
    queue = sx.bus.subscribe()
    ids = await sx.orchestrator.submit("quanto está o dólar e a petrobras?")
    await collect_until_done(queue)
    result = sx.conversations.api_messages(ids["conversation_id"])[2]["content"][0]
    data = json.loads(result["content"])
    assert {q["symbol"] for q in data["cotacoes"]} == {"USD", "PETR4"}
    assert all(q["source"] for q in data["cotacoes"])


async def test_ai_tool_alert_create(sx):
    provider = sx.provider_for_tests
    provider.add(
        [tool_use("t1", "alert_create", {"kind": "preco_abaixo", "symbol": "BTC", "value": 300000})],
        stop_reason="tool_use",
    ).add([text("Alerta criado.")])
    queue = sx.bus.subscribe()
    await sx.orchestrator.submit("me avise se o bitcoin cair abaixo de 300 mil")
    await collect_until_done(queue)
    assert sx.alerts.list()[0]["label"] == "BTC abaixo de 300000"


def test_api_overview_alerts_and_briefings(sx):
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(create_app(sexta=sx)) as client:
        overview = client.get("/api/intel/overview", headers=auth).json()
        assert overview["weather"]["place"]["name"] == "São Paulo"
        assert overview["news"]["brasil"]["items"]
        assert overview["indicators"]["items"]
        created = client.post(
            "/api/alerts", json={"kind": "variacao", "params": {"symbol": "USD", "pct": 0.5}}, headers=auth
        ).json()
        assert (
            client.patch(f"/api/alerts/{created['id']}", json={"enabled": False}, headers=auth).json()["enabled"]
            is False
        )
        assert client.post("/api/alerts", json={"kind": "preco_acima", "params": {}}, headers=auth).status_code == 400
        assert client.delete(f"/api/alerts/{created['id']}", headers=auth).json()["status"] == "ok"
        spark = client.get("/api/intel/histories", params={"symbols": "PETR4,XXXX9"}, headers=auth).json()
        assert spark["PETR4"]["closes"] and "error" in spark["XXXX9"]
        assert (
            client.get("/api/intel/news", params={"q": "eleições"}, headers=auth).json()["source"] == "Google Notícias"
        )
