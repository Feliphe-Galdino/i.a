"""Guardas da automação de sites (regras no código, não no prompt).

* **Endereços:** só ``http``/``https``; nada de rede local (127.x, 10.x, 192.168.x,
  169.254.x — inclui o servidor da própria Sexta-Feira e metadados de nuvem), nem
  ``file:``, ``javascript:`` ou páginas internas do navegador. Vale para a navegação
  e para cada requisição que a página fizer (imagens, scripts, fetch).
* **Campos sensíveis:** a IA nunca digita senhas, códigos de verificação nem dados
  de cartão — você faz isso na janela do navegador.
* **Cliques:** comprar, pagar, enviar, publicar, excluir, assinar… são CRÍTICOS e
  sempre pedem sua confirmação; enviar formulários pede confirmação no nível padrão.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..memory.text import strip_accents
from ..security.permissions import Risk

BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")
DNS_CACHE_S = 60

SENSITIVE_RE = re.compile(
    r"senha|password|passwd|passcode|\bpin\b|cvv|cvc|security.?code|codigo de seguranca|"
    r"card.?number|numero do cartao|cartao de credito|credit.?card|cc-?(num|number|csc|exp)|"
    r"one.?time|otp|token|2fa|codigo de verificacao|verification code",
)
SENSITIVE_AUTOCOMPLETE = ("password", "cc-", "one-time-code")
SEARCH_RE = re.compile(r"\b(busca|buscar|pesquisa|pesquisar|procurar|search|filtrar|filtro|q)\b")
CRITICAL_RE = re.compile(
    r"\b(comprar|compre|compra|finalizar|fechar pedido|confirmar (pedido|compra|pagamento|envio|transferencia)|"
    r"pagar|pague|pagamento|checkout|carrinho de compras|assinar|assine|assinatura|contratar|contrate|"
    r"transferir|transferencia|pix|doar|doacao|enviar|envie|send|publicar|postar|post|tweet|tuitar|"
    r"excluir|apagar|deletar|delete|remover|remove|descadastrar|unsubscribe|cancelar (conta|assinatura|plano)|"
    r"buy|purchase|pay|place order|order now|subscribe|donate|sign up|cadastrar|cadastre-se|criar conta)\b"
)


class BrowserGuardError(Exception):
    """Ação bloqueada pelas guardas do navegador."""


def _host_allowed_literal(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return ip.is_global and not ip.is_multicast


@dataclass
class UrlGuard:
    """Valida endereços. ``allow`` libera ``host:porta`` específicos (usado só em testes)."""

    allow: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        self._dns: dict[str, tuple[float, bool]] = {}

    def check(self, url: str, *, resolve: bool = True) -> str | None:
        """Retorna o motivo do bloqueio, ou ``None`` se o endereço é permitido."""
        try:
            parts = urlsplit(url)
        except ValueError:
            return "endereço inválido"
        scheme = (parts.scheme or "").lower()
        if scheme not in ("http", "https"):
            return f"só endereços http(s) são permitidos (recebido: {scheme or 'sem protocolo'}:)"
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            return "endereço sem domínio"
        port = parts.port or (443 if scheme == "https" else 80)
        if f"{host}:{port}" in self.allow:
            return None
        if parts.username or parts.password:
            return "endereços com usuário/senha embutidos não são permitidos"
        if host == "localhost" or host.endswith(BLOCKED_SUFFIXES) or "." not in host and ":" not in host:
            return "endereços da rede local não são permitidos"
        if not _host_allowed_literal(host):
            return "endereços da rede local ou reservados não são permitidos"
        if resolve and not self._resolves_public(host):
            return f"{host} aponta para a rede local"
        return None

    def _resolves_public(self, host: str) -> bool:
        try:
            ipaddress.ip_address(host)
            return True  # já checado como literal
        except ValueError:
            pass
        cached = self._dns.get(host)
        if cached and time.monotonic() - cached[0] < DNS_CACHE_S:
            return cached[1]
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            ok = all(_host_allowed_literal(info[4][0].split("%")[0]) for info in infos)
        except OSError:
            ok = True  # sem DNS local (ex.: atrás de proxy): a conexão em si decide
        self._dns[host] = (time.monotonic(), ok)
        return ok


def _norm(*values: str) -> str:
    return strip_accents(" ".join(v for v in values if v).lower())


def is_sensitive_field(el: dict) -> bool:
    if (el.get("type") or "").lower() == "password":
        return True
    autocomplete = (el.get("autocomplete") or "").lower()
    if any(token in autocomplete for token in SENSITIVE_AUTOCOMPLETE):
        return True
    return bool(
        SENSITIVE_RE.search(_norm(el.get("name", ""), el.get("id", ""), el.get("label", ""), el.get("text", "")))
    )


def is_search_field(el: dict) -> bool:
    if (el.get("type") or "").lower() == "search" or (el.get("role") or "") == "searchbox":
        return True
    return bool(SEARCH_RE.search(_norm(el.get("name", ""), el.get("id", ""), el.get("label", ""), el.get("text", ""))))


def describe_element(el: dict) -> str:
    kind = {
        "a": "link",
        "button": "botão",
        "select": "lista",
        "textarea": "caixa de texto",
        "summary": "seção expansível",
    }.get(el.get("tag", ""), "")
    if el.get("tag") == "input":
        kind = {"submit": "botão", "button": "botão", "checkbox": "caixa de seleção", "radio": "opção"}.get(
            (el.get("type") or "").lower(), "campo"
        )
    if not kind:
        kind = el.get("role") or el.get("tag") or "elemento"
    label = el.get("text") or el.get("label") or el.get("name") or ""
    return f'{kind} "{label[:80]}"' if label else kind


def click_risk(el: dict) -> tuple[Risk, str]:
    """Risco de clicar num elemento, pelo texto e pelo tipo."""
    text = _norm(el.get("text", ""), el.get("label", ""), el.get("name", ""), el.get("id", ""))
    if CRITICAL_RE.search(text):
        return Risk.CRITICAL, "parece concluir uma compra, envio, publicação, cadastro ou exclusão"
    submits = (el.get("type") or "").lower() == "submit" or (
        el.get("tag") == "button" and el.get("form") and (el.get("type") or "submit").lower() == "submit"
    )
    if submits and not SEARCH_RE.search(text):
        return Risk.WRITE, "envia um formulário"
    return Risk.READ, "navegação"
