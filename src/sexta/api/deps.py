"""Autenticação da API local.

Mesmo rodando só em 127.0.0.1, outros programas e páginas abertas no navegador
poderiam tentar falar com a Sexta-Feira. Por isso toda rota exige um token secreto
(gerado na primeira execução e exibido no terminal), além da verificação do
cabeçalho Host/Origin contra *DNS rebinding*.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request, WebSocket, status

from ..container import Sexta


def get_sexta(request: Request) -> Sexta:
    return request.app.state.sexta


def _token_ok(supplied: str | None, expected: str) -> bool:
    return bool(supplied) and secrets.compare_digest(supplied.encode(), expected.encode())


def require_token(request: Request) -> None:
    sexta: Sexta = request.app.state.sexta
    header = request.headers.get("authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("x-sexta-token")
    if not _token_ok(supplied, sexta.settings.token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de acesso inválido ou ausente.")


def websocket_authorized(ws: WebSocket) -> bool:
    sexta: Sexta = ws.app.state.sexta
    if not _token_ok(ws.query_params.get("token"), sexta.settings.token):
        return False
    origin = ws.headers.get("origin")
    if origin:
        host = urlparse(origin).hostname or ""
        if host not in sexta.settings.host_allowlist:
            return False
    return True
