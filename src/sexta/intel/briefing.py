"""Resumos periódicos ("briefings"): clima, mercado, indicadores, notícias e alertas.

Os dados são coletados primeiro (determinístico, com fontes e horários) e depois a IA
escreve o resumo numa conversa própria ("Resumos"). Sem IA disponível, usamos um
modelo de texto fixo — o resumo nunca deixa de sair.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ..memory.db import Database, utcnow
from . import feeds

log = logging.getLogger(__name__)

PROMPT = """Escreva o meu resumo {kind} usando APENAS os dados abaixo (coletados em {when}).

Regras:
- Comece com UMA linha de manchete (sem título Markdown), resumindo o mais importante.
- Seções curtas: Clima · Mercado e economia · Notícias (Brasil, mundo, tecnologia/IA) · Tendências · Alertas.
- Cite a fonte e o horário dos números. Separe FATOS de ESTIMATIVAS; não faça recomendação de compra/venda.
- Se alguma parte falhou ou está desatualizada, diga isso em uma frase.
- No máximo ~300 palavras.

DADOS:
{data}
"""


def _fmt_number(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(value)


def compact_pack(overview: dict[str, Any], alerts: list[dict]) -> dict[str, Any]:
    """Reduz a visão geral ao essencial (economiza tokens)."""
    pack: dict[str, Any] = {}
    w = overview.get("weather")
    if w and not w.get("error"):
        pack["clima"] = {
            "local": f"{w['place']['name']}, {w['place'].get('admin1') or ''}".strip(", "),
            "agora": w["current"],
            "proximos_dias": w["daily"][:3],
            "avisos": w.get("risks", []),
            "fonte": w.get("source"),
            "atualizado": w.get("fetched_at"),
        }
    q = overview.get("quotes") or {}
    if q.get("quotes"):
        pack["mercado"] = {
            "cotacoes": [
                {k: c.get(k) for k in ("label", "price", "currency", "change_pct", "time", "source")}
                for c in q["quotes"]
            ],
            "falhas": q.get("errors") or [],
        }
    ind = overview.get("indicators") or {}
    if ind.get("items"):
        pack["indicadores"] = [i for i in ind["items"] if not i.get("error")]
    pack["noticias"] = {
        topic: [
            {"titulo": i["title"], "fonte": i["source"], "quando": i.get("published")}
            for i in (n.get("items") or [])[:4]
        ]
        for topic, n in (overview.get("news") or {}).items()
        if isinstance(n, dict)
    }
    tr = overview.get("trends") or {}
    if tr.get("items"):
        pack["tendencias"] = [t["title"] for t in tr["items"][:8]]
    if alerts:
        pack["alertas_24h"] = [{"titulo": a["title"], "mensagem": a["message"], "quando": a["ts"]} for a in alerts[:5]]
    return pack


def template_text(pack: dict[str, Any], when: str) -> str:
    """Resumo sem IA (modo offline ou falha da API)."""
    lines = [f"Resumo de {when}"]
    clima = pack.get("clima")
    if clima:
        now = clima["agora"]
        lines.append(f"\n**Clima — {clima['local']}:** {_fmt_number(now.get('temp'), 0)} °C, {now.get('desc')}.")
        for day in clima["proximos_dias"][:2]:
            lines.append(
                f"- {day['date']}: {_fmt_number(day.get('tmin'), 0)}–{_fmt_number(day.get('tmax'), 0)} °C, {day.get('desc')}"
            )
        for risk in clima.get("avisos", []):
            lines.append(f"- ⚠ {risk}")
    mercado = pack.get("mercado")
    if mercado:
        lines.append("\n**Mercado:**")
        for c in mercado["cotacoes"]:
            change = c.get("change_pct")
            lines.append(
                f"- {c['label']}: {_fmt_number(c['price'])} {c.get('currency') or ''} ({'+' if (change or 0) >= 0 else ''}{_fmt_number(change)}%)"
            )
    if pack.get("indicadores"):
        lines.append(
            "\n**Indicadores (Banco Central):** "
            + "; ".join(
                f"{i['name']} {_fmt_number(i['value'])}{i['unit'] if i['unit'].startswith('%') else ''}"
                for i in pack["indicadores"][:4]
            )
        )
    for topic, items in (pack.get("noticias") or {}).items():
        if items:
            lines.append(f"\n**{feeds.CATEGORY_LABELS.get(topic, topic)}:**")
            lines.extend(f"- {i['titulo']} ({i['fonte']})" for i in items[:3])
    if pack.get("tendencias"):
        lines.append("\n**Em alta no Google:** " + ", ".join(pack["tendencias"][:6]))
    if pack.get("alertas_24h"):
        lines.append("\n**Alertas:**")
        lines.extend(f"- {a['titulo']}: {a['mensagem']}" for a in pack["alertas_24h"])
    return "\n".join(lines)


class BriefingService:
    def __init__(self, db: Database, intel: Any, alerts: Any, orchestrator: Any, bus: Any):
        self.db = db
        self.intel = intel
        self.alerts = alerts
        self.orchestrator = orchestrator
        self.bus = bus

    def latest(self) -> dict | None:
        rows = self.list(1)
        return rows[0] if rows else None

    def list(self, limit: int = 10) -> list[dict]:
        rows = self.db.query("SELECT * FROM briefings ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["data"] = json.loads(row["data"] or "{}")
        return rows

    async def generate(self, kind: str = "diário") -> dict:
        overview = await self.intel.overview()
        recent_alerts = self.alerts.events(10)
        pack = compact_pack(overview, recent_alerts)
        when = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
        text, task_id, conversation_id = "", None, None
        if getattr(self.orchestrator, "offline", True) is False:
            try:
                conversation_id = self.intel.cache.get("briefing_conversation")
                if conversation_id and self.orchestrator.conversations.get(conversation_id) is None:
                    conversation_id = None
                prompt = PROMPT.format(kind=kind, when=when, data=json.dumps(pack, ensure_ascii=False, indent=1))
                ids = await self.orchestrator.submit(prompt, conversation_id=conversation_id, mode="equilibrado")
                conversation_id, task_id = ids["conversation_id"], ids["task_id"]
                self.intel.cache.set("briefing_conversation", conversation_id)
                result = await self.orchestrator.wait(task_id)
                if result.get("status") == "done":
                    text = result.get("text") or ""
            except Exception as exc:  # noqa: BLE001
                log.warning("Resumo pela IA falhou; usando modelo fixo: %s", exc)
        if not text.strip():
            text = template_text(pack, when)
        headline = next((line.strip("#* ").strip() for line in text.splitlines() if line.strip()), "Resumo")
        cur = self.db.execute(
            "INSERT INTO briefings (ts, kind, headline, text, data, task_id, conversation_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                utcnow(),
                kind,
                headline[:200],
                text,
                json.dumps(pack, ensure_ascii=False, default=str),
                task_id,
                conversation_id,
            ),
        )
        briefing = {"id": int(cur.lastrowid), "headline": headline[:200], "text": text, "kind": kind}
        await self.bus.publish({"type": "briefing_ready", **briefing})
        return briefing
