"""``web_fetch``: baixa uma página sem navegador (rápido e barato) com as mesmas guardas."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from .guards import BrowserGuardError, UrlGuard
from .readable import html_to_text

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SextaFeira/0.4 (assistente pessoal)",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
}


class WebFetcher:
    def __init__(self, guard: UrlGuard, transport: httpx.AsyncBaseTransport | None = None):
        self.guard = guard
        self.transport = transport

    async def fetch(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self.transport, timeout=20, follow_redirects=False, headers=HEADERS
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                reason = self.guard.check(url)  # cada salto do redirecionamento é conferido
                if reason:
                    raise BrowserGuardError(reason)
                async with client.stream("GET", url) as response:
                    if response.is_redirect and response.headers.get("location"):
                        url = urljoin(url, response.headers["location"])
                        continue
                    body = b""
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                    ctype = response.headers.get("content-type", "")
                    text = body.decode(response.encoding or "utf-8", errors="replace")
                    if "html" in ctype or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
                        title, text = html_to_text(text)
                    elif "json" in ctype or ctype.startswith("text/"):
                        title = ""
                    else:
                        raise BrowserGuardError(f"tipo de conteúdo não suportado: {ctype or 'desconhecido'}")
                    return {"url": str(response.url), "status": response.status_code, "title": title, "text": text}
            raise BrowserGuardError("redirecionamentos demais")
