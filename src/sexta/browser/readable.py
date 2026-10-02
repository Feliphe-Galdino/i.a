"""Leitura simples de páginas sem navegador (``web_fetch``): HTML → texto legível."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "footer", "form"}
BLOCK = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "br",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "main",
    "pre",
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in SKIP:
            self._skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3") and not self._skip:
            self.parts.append("## ")
        if tag == "li" and not self._skip:
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in SKIP and self._skip:
            self._skip -= 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Retorna (título, texto) com parágrafos preservados."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — HTML quebrado: devolve o que deu para ler
        pass
    text = unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return " ".join(parser.title.split()), text
