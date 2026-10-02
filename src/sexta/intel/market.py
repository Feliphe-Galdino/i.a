"""Mercado financeiro e indicadores econômicos (fontes gratuitas, sem chave).

* Banco Central do Brasil — SGS (oficial): Selic, IPCA, CDI, PTAX, IGP-M.
* AwesomeAPI (economia.awesomeapi.com.br): câmbio.
* CoinGecko: criptomoedas.
* Yahoo Finance (não oficial, ~15 min de atraso na B3): ações e índices.

As estatísticas (médias móveis, volatilidade, queda máxima) são ESTIMATIVAS técnicas
calculadas sobre o histórico — nunca previsões ou garantias de retorno.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

from .http import FetchError, HttpClient

SOURCES = {
    "yahoo": "Yahoo Finance (não oficial; B3 com atraso de ~15 min)",
    "awesome": "AwesomeAPI (economia.awesomeapi.com.br)",
    "coingecko": "CoinGecko (coingecko.com)",
    "bcb": "Banco Central do Brasil — SGS (oficial)",
}

ALIASES: dict[str, tuple[str, str, str]] = {
    "ibov": ("yahoo", "^BVSP", "Ibovespa"),
    "ibovespa": ("yahoo", "^BVSP", "Ibovespa"),
    "^bvsp": ("yahoo", "^BVSP", "Ibovespa"),
    "sp500": ("yahoo", "^GSPC", "S&P 500"),
    "s&p500": ("yahoo", "^GSPC", "S&P 500"),
    "nasdaq": ("yahoo", "^IXIC", "Nasdaq"),
    "dow": ("yahoo", "^DJI", "Dow Jones"),
    "ifix": ("yahoo", "IFIX.SA", "IFIX"),
    "usd": ("awesome", "USD-BRL", "Dólar"),
    "dolar": ("awesome", "USD-BRL", "Dólar"),
    "dólar": ("awesome", "USD-BRL", "Dólar"),
    "usdbrl": ("awesome", "USD-BRL", "Dólar"),
    "eur": ("awesome", "EUR-BRL", "Euro"),
    "euro": ("awesome", "EUR-BRL", "Euro"),
    "gbp": ("awesome", "GBP-BRL", "Libra"),
    "libra": ("awesome", "GBP-BRL", "Libra"),
    "btc": ("coingecko", "bitcoin", "Bitcoin"),
    "bitcoin": ("coingecko", "bitcoin", "Bitcoin"),
    "eth": ("coingecko", "ethereum", "Ethereum"),
    "ethereum": ("coingecko", "ethereum", "Ethereum"),
    "sol": ("coingecko", "solana", "Solana"),
    "solana": ("coingecko", "solana", "Solana"),
    "xrp": ("coingecko", "ripple", "XRP"),
    "usdt": ("coingecko", "tether", "Tether"),
}

INDICATORS = [
    (432, "Selic (meta)", "% a.a."),
    (13522, "IPCA (12 meses)", "%"),
    (433, "IPCA (mês)", "%"),
    (4389, "CDI (anualizado)", "% a.a."),
    (1, "Dólar PTAX (venda)", "R$"),
    (189, "IGP-M (mês)", "%"),
]

_B3 = re.compile(r"^[A-Z]{4}\d{1,2}[A-Z]?$")


def resolve_symbol(raw: str) -> tuple[str, str, str]:
    """Converte o que o usuário digita em (provedor, código, nome)."""
    text = raw.strip()
    key = text.lower().replace(" ", "")
    if key in ALIASES:
        return ALIASES[key]
    upper = text.upper()
    if _B3.match(upper):
        return ("yahoo", f"{upper}.SA", upper)
    if "-" in upper and len(upper) == 7 and upper.endswith("-BRL"):
        return ("awesome", upper, upper)
    return ("yahoo", upper, upper)


def _ts(epoch: float | int | str | None) -> str | None:
    if epoch in (None, ""):
        return None
    return datetime.fromtimestamp(float(epoch), UTC).isoformat(timespec="seconds")


async def _yahoo_chart(http: HttpClient, code: str, range_: str = "5d", interval: str = "1d") -> dict[str, Any]:
    data = await http.json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{code}", {"range": range_, "interval": interval}
    )
    result = ((data.get("chart") or {}).get("result") or [None])[0]
    if not result:
        error = (data.get("chart") or {}).get("error") or {}
        raise FetchError(error.get("description") or f"sem dados para {code}")
    return result


def _previous_close(result: dict[str, Any]) -> float | None:
    """Fechamento do último pregão ANTES do dia da cotação atual.

    Cuidado: com ``range=5d`` o ``chartPreviousClose`` do Yahoo é o fechamento de 5 dias
    atrás (anterior ao gráfico), não o de ontem — usá-lo daria a variação da semana.
    """
    meta = result.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)  # fuso da bolsa, para comparar datas locais
    stamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    market_time = meta.get("regularMarketTime")
    if market_time:
        today = datetime.fromtimestamp(int(market_time) + offset, UTC).date()
        prior = [
            c
            for t, c in zip(stamps, closes, strict=False)
            if c is not None and datetime.fromtimestamp(int(t) + offset, UTC).date() < today
        ]
        if prior:
            return float(prior[-1])
    fallback = meta.get("previousClose") or meta.get("chartPreviousClose")
    return float(fallback) if fallback else None


async def quotes(http: HttpClient, symbols: list[str]) -> dict[str, Any]:
    resolved = [(raw, *resolve_symbol(raw)) for raw in symbols]
    out: list[dict[str, Any]] = []
    errors: list[str] = []

    awesome = [r for r in resolved if r[1] == "awesome"]
    if awesome:
        try:
            pairs = ",".join(code for _, _, code, _ in awesome)
            data = await http.json(f"https://economia.awesomeapi.com.br/json/last/{pairs}")
            for raw, _prov, code, label in awesome:
                item = data.get(code.replace("-", ""))
                if not item:
                    errors.append(f"{raw}: sem cotação")
                    continue
                out.append(
                    {
                        "symbol": raw,
                        "label": label,
                        "price": float(item["bid"]),
                        "currency": "BRL",
                        "change_pct": float(item.get("pctChange") or 0),
                        "time": _ts(item.get("timestamp")),
                        "source": SOURCES["awesome"],
                        "kind": "moeda",
                    }
                )
        except (FetchError, KeyError, ValueError) as exc:
            errors.append(f"câmbio: {exc}")

    crypto = [r for r in resolved if r[1] == "coingecko"]
    if crypto:
        try:
            ids = ",".join(code for _, _, code, _ in crypto)
            data = await http.json(
                "https://api.coingecko.com/api/v3/simple/price",
                {
                    "ids": ids,
                    "vs_currencies": "brl,usd",
                    "include_24hr_change": "true",
                    "include_last_updated_at": "true",
                },
            )
            for raw, _prov, code, label in crypto:
                item = data.get(code)
                if not item:
                    errors.append(f"{raw}: sem cotação")
                    continue
                out.append(
                    {
                        "symbol": raw,
                        "label": label,
                        "price": float(item["brl"]),
                        "price_usd": item.get("usd"),
                        "currency": "BRL",
                        "change_pct": round(float(item.get("brl_24h_change") or 0), 2),
                        "time": _ts(item.get("last_updated_at")),
                        "source": SOURCES["coingecko"],
                        "kind": "cripto",
                    }
                )
        except (FetchError, KeyError, ValueError) as exc:
            errors.append(f"cripto: {exc}")

    for raw, prov, code, label in resolved:
        if prov != "yahoo":
            continue
        try:
            result = await _yahoo_chart(http, code)
            meta = result["meta"]
            price = float(meta["regularMarketPrice"])
            previous = _previous_close(result)
            change = round((price / float(previous) - 1) * 100, 2) if previous else None
            out.append(
                {
                    "symbol": raw,
                    "label": meta.get("shortName") or label,
                    "price": price,
                    "currency": meta.get("currency") or "",
                    "change_pct": change,
                    "time": _ts(meta.get("regularMarketTime")),
                    "source": SOURCES["yahoo"],
                    "kind": "indice" if code.startswith("^") else "acao",
                }
            )
        except (FetchError, KeyError, ValueError, TypeError) as exc:
            errors.append(f"{raw}: {exc}")
    order = {raw: i for i, raw in enumerate(symbols)}
    out.sort(key=lambda q: order.get(q["symbol"], 99))
    return {"quotes": out, "errors": errors}


def compute_stats(closes: list[float]) -> dict[str, Any]:
    values = [float(c) for c in closes if c is not None and not math.isnan(float(c))]
    if len(values) < 2:
        return {"points": len(values)}
    last, first = values[-1], values[0]
    returns = [math.log(b / a) for a, b in zip(values, values[1:], strict=False) if a > 0 and b > 0]
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    peak, max_dd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    sma = lambda n: round(sum(values[-n:]) / n, 4) if len(values) >= n else None  # noqa: E731
    sma20, sma50 = sma(20), sma(50)
    if sma20 and sma50:
        trend = "alta" if last > sma20 > sma50 else "baixa" if last < sma20 < sma50 else "lateral"
    elif sma20:
        trend = "alta" if last > sma20 else "baixa"
    else:
        trend = "indefinida"
    return {
        "points": len(values),
        "last": round(last, 4),
        "first": round(first, 4),
        "change_period_pct": round((last / first - 1) * 100, 2) if first else None,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "sma20": sma20,
        "sma50": sma50,
        "volatility_annual_pct": round(math.sqrt(variance) * math.sqrt(252) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trend": trend,
        "note": "Estimativas técnicas sobre o histórico; não são previsões nem recomendação.",
    }


PERIODS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}


async def history(http: HttpClient, symbol: str, period: str = "3mo") -> dict[str, Any]:
    period = period if period in PERIODS else "3mo"
    provider, code, label = resolve_symbol(symbol)
    dates: list[str] = []
    closes: list[float] = []
    if provider == "yahoo":
        result = await _yahoo_chart(http, code, period, "1d")
        stamps = result.get("timestamp") or []
        raw = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        for stamp, close in zip(stamps, raw, strict=False):
            if close is not None:
                dates.append(datetime.fromtimestamp(stamp, UTC).date().isoformat())
                closes.append(float(close))
        label = result.get("meta", {}).get("shortName") or label
    elif provider == "coingecko":
        data = await http.json(
            f"https://api.coingecko.com/api/v3/coins/{code}/market_chart",
            {"vs_currency": "brl", "days": PERIODS[period], "interval": "daily"},
        )
        for stamp, price in data.get("prices") or []:
            dates.append(datetime.fromtimestamp(stamp / 1000, UTC).date().isoformat())
            closes.append(float(price))
    else:
        data = await http.json(f"https://economia.awesomeapi.com.br/json/daily/{code}/{PERIODS[period]}")
        for item in reversed(data or []):
            dates.append(datetime.fromtimestamp(int(item["timestamp"]), UTC).date().isoformat())
            closes.append(float(item["bid"]))
    if not closes:
        raise FetchError(f"sem histórico para {symbol}")
    return {
        "symbol": symbol,
        "label": label,
        "period": period,
        "dates": dates,
        "closes": [round(c, 4) for c in closes],
        "stats": compute_stats(closes),
        "source": SOURCES[provider],
    }


async def indicators(http: HttpClient) -> list[dict[str, Any]]:
    out = []
    for code, name, unit in INDICATORS:
        try:
            data = await http.json(
                f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/2", {"formato": "json"}
            )
            if not data:
                continue
            last = data[-1]
            previous = data[-2] if len(data) > 1 else None
            out.append(
                {
                    "code": code,
                    "name": name,
                    "value": float(last["valor"]),
                    "unit": unit,
                    "date": last["data"],
                    "previous": float(previous["valor"]) if previous else None,
                    "source": SOURCES["bcb"],
                }
            )
        except (FetchError, KeyError, ValueError) as exc:
            out.append({"code": code, "name": name, "error": str(exc), "source": SOURCES["bcb"]})
    return out
