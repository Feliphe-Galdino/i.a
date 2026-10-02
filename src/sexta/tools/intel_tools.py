"""Ferramentas de informação: notícias, tendências, clima, mercado, indicadores e alertas.

Todas devolvem fonte e horário de atualização. O conteúdo vem da internet: é DADO,
não instrução (o system prompt reforça isso).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..intel.alerts import KINDS
from ..intel.feeds import CATEGORY_LABELS
from ..intel.http import FetchError
from ..security.permissions import Risk
from .base import Assessment, Tool, ToolContext, ToolOutput

Category = Literal["brasil", "mundo", "politica", "economia", "tecnologia", "ia", "ciencia"]


def _intel(ctx: ToolContext):
    intel = getattr(ctx, "intel", None)
    if intel is None:
        raise FetchError("serviço de informações indisponível")
    return intel


def _err(exc: Exception) -> ToolOutput:
    return ToolOutput(f"Não consegui obter os dados: {exc}", is_error=True)


class NewsArgs(BaseModel):
    category: Category = Field(
        default="brasil", description="; ".join(f"{k} = {v}" for k, v in CATEGORY_LABELS.items())
    )
    limit: int = Field(default=8, ge=1, le=25)


async def news_latest(args: NewsArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).news(args.category, args.limit)
    except FetchError as exc:
        return _err(exc)
    return {
        "categoria": data["label"],
        "atualizado_em": data["fetched_at"],
        "fontes": data["sources"],
        "noticias": [
            {
                "titulo": i["title"],
                "fonte": i["source"],
                "publicado": i["published"],
                "resumo": i["summary"],
                "link": i["link"],
            }
            for i in data["items"]
        ],
        "avisos": data["errors"],
    }


class NewsSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=120, description="Assunto a procurar nas notícias (Google Notícias).")
    limit: int = Field(default=8, ge=1, le=20)


async def news_search(args: NewsSearchArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).news_search(args.query, args.limit)
    except FetchError as exc:
        return _err(exc)
    return {
        "busca": data["query"],
        "fonte": data["source"],
        "atualizado_em": data["fetched_at"],
        "noticias": [
            {
                "titulo": i["title"],
                "fonte_original": i["summary"][:80] or i["source"],
                "publicado": i["published"],
                "link": i["link"],
            }
            for i in data["items"]
        ],
    }


class TrendsArgs(BaseModel):
    limit: int = Field(default=15, ge=1, le=30)


async def trends(args: TrendsArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).trends(args.limit)
    except FetchError as exc:
        return _err(exc)
    return {
        "fonte": data["source"],
        "atualizado_em": data["fetched_at"],
        "em_alta": [{"assunto": i["title"], "buscas": i.get("traffic")} for i in data["items"]],
    }


class WeatherArgs(BaseModel):
    city: str | None = Field(
        default=None, max_length=80, description="Cidade (vazio = cidade configurada pelo usuário)."
    )
    days: int = Field(default=3, ge=1, le=7)


async def weather_forecast(args: WeatherArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).weather(args.city, args.days)
    except FetchError as exc:
        return _err(exc)
    return {
        "local": data["place"],
        "agora": data["current"],
        "previsao": data["daily"],
        "avisos_estimados": data["risks"],
        "fonte": data["source"],
        "atualizado_em": data["fetched_at"],
    }


class QuotesArgs(BaseModel):
    symbols: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Ativos: ações da B3 (PETR4), EUA (AAPL), índices (IBOV, SP500, NASDAQ), moedas (USD, EUR), cripto (BTC, ETH). Vazio = lista do usuário.",
    )


async def market_quotes(args: QuotesArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).quotes(args.symbols or None)
    except FetchError as exc:
        return _err(exc)
    return {"cotacoes": data["quotes"], "falhas": data["errors"], "consultado_em": data["fetched_at"]}


class HistoryArgs(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    period: Literal["1mo", "3mo", "6mo", "1y"] = "3mo"


async def market_history(args: HistoryArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).history(args.symbol, args.period)
    except FetchError as exc:
        return _err(exc)
    closes = data["closes"]
    step = max(1, len(closes) // 30)  # amostra para economizar tokens
    return {
        "ativo": data["label"],
        "periodo": data["period"],
        "estatisticas_estimadas": data["stats"],
        "fechamentos_amostrados": [
            {"data": d, "fechamento": c} for d, c in list(zip(data["dates"], closes, strict=False))[::step]
        ],
        "fonte": data["source"],
        "atualizado_em": data["fetched_at"],
    }


class NoArgs(BaseModel):
    pass


async def economic_indicators(args: NoArgs, ctx: ToolContext):
    try:
        data = await _intel(ctx).indicators()
    except FetchError as exc:
        return _err(exc)
    return {"indicadores": data["items"], "consultado_em": data["fetched_at"]}


async def daily_overview(args: NoArgs, ctx: ToolContext):
    from ..intel.briefing import compact_pack

    intel = _intel(ctx)
    overview = await intel.overview()
    alerts = getattr(ctx, "alerts", None)
    return compact_pack(overview, alerts.events(5) if alerts else [])


class AlertCreateArgs(BaseModel):
    kind: Literal["preco_acima", "preco_abaixo", "variacao", "noticia", "clima"] = Field(
        description="; ".join(f"{k} = {v}" for k, v in KINDS.items())
    )
    symbol: str | None = Field(default=None, description="Ativo (preço/variação): PETR4, BTC, USD, IBOV…")
    value: float | None = Field(default=None, description="Valor de referência (preço).")
    pct: float | None = Field(default=None, description="Variação diária em % (variacao).")
    keywords: list[str] | None = Field(default=None, description="Palavras-chave (noticia).")
    rain_mm: float | None = None
    temp_max: float | None = None
    temp_min: float | None = None
    wind_kmh: float | None = None
    label: str = Field(default="", max_length=120)
    cooldown_h: float = Field(default=6, ge=0.1, le=168, description="Horas mínimas entre dois avisos.")


async def alert_create(args: AlertCreateArgs, ctx: ToolContext):
    alerts = getattr(ctx, "alerts", None)
    if alerts is None:
        return ToolOutput("Alertas indisponíveis.", is_error=True)
    params = args.model_dump(exclude={"kind", "label", "cooldown_h"}, exclude_none=True)
    try:
        alert = alerts.create(args.kind, params, label=args.label, cooldown_h=args.cooldown_h)
    except ValueError as exc:
        return ToolOutput(f"Alerta inválido: {exc}", is_error=True)
    await ctx.publish({"type": "alerts_changed"})
    return f"Alerta criado (#{alert['id']}): {alert['label']}. Verificado a cada 5 minutos."


async def alert_list(args: NoArgs, ctx: ToolContext):
    alerts = getattr(ctx, "alerts", None)
    if alerts is None:
        return ToolOutput("Alertas indisponíveis.", is_error=True)
    return {
        "alertas": [
            {"id": a["id"], "descricao": a["label"], "ativo": a["enabled"], "ultimo_disparo": a["last_triggered_at"]}
            for a in alerts.list()
        ],
        "disparos_recentes": [
            {"quando": e["ts"], "titulo": e["title"], "mensagem": e["message"]} for e in alerts.events(5)
        ],
    }


class AlertDeleteArgs(BaseModel):
    id: int


def _assess_alert_delete(args: AlertDeleteArgs, ctx: ToolContext) -> Assessment:
    alerts = getattr(ctx, "alerts", None)
    alert = alerts.get(args.id) if alerts else None
    return Assessment(Risk.WRITE, summary=f"Excluir o alerta #{args.id}" + (f": {alert['label']}" if alert else ""))


async def alert_delete(args: AlertDeleteArgs, ctx: ToolContext):
    alerts = getattr(ctx, "alerts", None)
    if alerts is None or not alerts.delete(args.id):
        return ToolOutput(f"Alerta {args.id} não encontrado.", is_error=True)
    await ctx.publish({"type": "alerts_changed"})
    return f"Alerta {args.id} excluído."


TOOLS = [
    Tool(
        "news_latest",
        "Últimas notícias de uma categoria (feeds de G1, Agência Brasil, BBC, InfoMoney, Tecnoblog…), com fonte e horário.",
        NewsArgs,
        "intel.read",
        Risk.READ,
        news_latest,
    ),
    Tool(
        "news_search",
        "Procura notícias recentes sobre um assunto (Google Notícias).",
        NewsSearchArgs,
        "intel.read",
        Risk.READ,
        news_search,
    ),
    Tool(
        "trends", "Assuntos em alta nas buscas no Brasil (Google Trends).", TrendsArgs, "intel.read", Risk.READ, trends
    ),
    Tool(
        "weather_forecast",
        "Clima atual e previsão (Open-Meteo), com avisos estimados de chuva forte, calor, frio e vento.",
        WeatherArgs,
        "intel.read",
        Risk.READ,
        weather_forecast,
    ),
    Tool(
        "market_quotes",
        "Cotações atuais de ações, índices, moedas e criptomoedas, com fonte e horário.",
        QuotesArgs,
        "intel.read",
        Risk.READ,
        market_quotes,
    ),
    Tool(
        "market_history",
        "Histórico de preços e estatísticas técnicas estimadas (médias, volatilidade, queda máxima, tendência).",
        HistoryArgs,
        "intel.read",
        Risk.READ,
        market_history,
    ),
    Tool(
        "economic_indicators",
        "Indicadores oficiais do Banco Central (Selic, IPCA, CDI, PTAX, IGP-M).",
        NoArgs,
        "intel.read",
        Risk.READ,
        economic_indicators,
    ),
    Tool(
        "daily_overview",
        "Panorama do dia de uma vez: clima, mercado, indicadores, notícias dos temas do usuário, tendências e alertas.",
        NoArgs,
        "intel.read",
        Risk.READ,
        daily_overview,
    ),
    Tool(
        "alert_create",
        "Cria um alerta: preço acima/abaixo, variação diária, notícia com palavra-chave ou clima.",
        AlertCreateArgs,
        "alerts.write",
        Risk.SAFE,
        alert_create,
    ),
    Tool("alert_list", "Lista os alertas e os disparos recentes.", NoArgs, "alerts.write", Risk.SAFE, alert_list),
    Tool(
        "alert_delete",
        "Exclui um alerta.",
        AlertDeleteArgs,
        "alerts.write",
        Risk.WRITE,
        alert_delete,
        _assess_alert_delete,
    ),
]
