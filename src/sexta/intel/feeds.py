"""Notícias e tendências por RSS/Atom (sem chave de API).

O XML vem da internet: usamos ``defusedxml`` (proteção contra XML malicioso) e tratamos
todo o texto como dado — nunca como instrução para a IA.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from defusedxml import ElementTree as SafeET


def google_news_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


FEEDS: dict[str, list[tuple[str, str]]] = {
    "brasil": [
        ("G1", "https://g1.globo.com/rss/g1/"),
        ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
    ],
    "mundo": [
        ("BBC Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml"),
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ],
    "politica": [
        ("G1 Política", "https://g1.globo.com/rss/g1/politica/"),
        ("Agência Brasil Política", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ],
    "economia": [
        ("InfoMoney", "https://www.infomoney.com.br/feed/"),
        ("G1 Economia", "https://g1.globo.com/rss/g1/economia/"),
    ],
    "tecnologia": [
        ("Tecnoblog", "https://tecnoblog.net/feed/"),
        ("Hacker News", "https://hnrss.org/frontpage"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ],
    "ia": [
        ("Google Notícias", google_news_url("inteligência artificial")),
        ("Hacker News", "https://hnrss.org/newest?q=AI+OR+LLM&points=40"),
    ],
    "ciencia": [
        ("G1 Ciência", "https://g1.globo.com/rss/g1/ciencia-e-saude/"),
    ],
}
CATEGORY_LABELS = {
    "brasil": "Brasil",
    "mundo": "Mundo",
    "politica": "Política",
    "economia": "Economia",
    "tecnologia": "Tecnologia",
    "ia": "Inteligência artificial",
    "ciencia": "Ciência e saúde",
}
TRENDS_URL = "https://trends.google.com/trending/rss?geo=BR"

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass
class FeedItem:
    title: str
    link: str
    source: str
    category: str
    published: str | None
    summary: str
    guid: str
    traffic: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def strip_html(text: str | None, limit: int = 300) -> str:
    clean = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text or ""))).strip()
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(element, *names: str) -> str | None:
    for child in element:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text
    return None


def parse_feed(xml_text: str, *, source: str, category: str, limit: int = 30) -> list[FeedItem]:
    root = SafeET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    entries = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    items: list[FeedItem] = []
    for entry in entries[:limit]:
        title = strip_html(_child_text(entry, "title"), 220)
        if not title:
            continue
        link = (_child_text(entry, "link") or "").strip()
        if not link:  # Atom: <link href="..."/>
            for child in entry:
                if _local(child.tag) == "link" and child.get("href"):
                    link = child.get("href")
                    if child.get("rel", "alternate") == "alternate":
                        break
        summary = strip_html(_child_text(entry, "description", "summary", "content"))
        published = _parse_date(_child_text(entry, "pubDate", "published", "updated", "date"))
        guid = (_child_text(entry, "guid", "id") or link or title).strip()
        traffic = _child_text(entry, "approx_traffic")
        items.append(
            FeedItem(
                title=title,
                link=link,
                source=source,
                category=category,
                published=published,
                summary=summary if summary != title else "",
                guid=hashlib.sha1(guid.encode("utf-8")).hexdigest()[:16],
                traffic=traffic.strip() if traffic else None,
            )
        )
    return items


def merge_items(groups: list[list[FeedItem]], limit: int) -> list[FeedItem]:
    """Junta feeds, remove duplicatas (mesmo título) e ordena do mais recente."""
    seen: set[str] = set()
    merged: list[FeedItem] = []
    for item in (i for group in groups for i in group):
        key = re.sub(r"\W+", " ", item.title.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged.sort(key=lambda i: i.published or "", reverse=True)
    return merged[:limit]
