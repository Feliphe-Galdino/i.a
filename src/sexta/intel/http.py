"""Cliente HTTP compartilhado das fontes de informação (timeouts, identificação, testes)."""

from __future__ import annotations

from typing import Any

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SextaFeira/0.3 (+assistente pessoal)"


class FetchError(Exception):
    """Falha ao consultar uma fonte externa (rede, HTTP, formato)."""


class HttpClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6"},
            transport=transport,
        )

    async def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise FetchError(f"sem resposta de {httpx.URL(url).host}: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise FetchError(f"{httpx.URL(url).host} respondeu {response.status_code}")
        return response

    async def json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.get(url, params)
        try:
            return response.json()
        except ValueError as exc:
            raise FetchError(f"resposta inválida de {httpx.URL(url).host}") from exc

    async def text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return (await self.get(url, params)).text

    async def aclose(self) -> None:
        await self._client.aclose()
