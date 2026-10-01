"""Utilidades de texto para busca (FTS5) em português."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset(
    """
    a o e é de da do das dos em no na nos nas um uma uns umas por para pra pro com sem que
    se não nao mais menos muito muita como qual quais quando onde quem ser estar ter fazer
    isso isto esse essa este esta aquele aquela eu tu ele ela nós nos vocês voce você eles
    elas me te lhe meu minha meus minhas seu sua seus suas ao aos à às já ja também tambem
    só so mas ou então entao sobre entre até ate depois antes agora aqui ali lá la sim
    pode poderia quero queria gostaria favor obrigado obrigada olá ola oi sexta feira
    the and for with this that from what how you your are was were have has
    """.split()
)

_WORD = re.compile(r"[\w]+", re.UNICODE)


def strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def normalize(text: str) -> str:
    """Forma canônica para detectar duplicatas (minúsculas, sem acentos/pontuação)."""
    return " ".join(_WORD.findall(strip_accents(text.lower())))


def keywords(text: str, *, limit: int = 12) -> list[str]:
    seen: list[str] = []
    for word in _WORD.findall(text.lower()):
        if len(word) < 3 or word in STOPWORDS or word.isdigit() and len(word) < 4:
            continue
        if word not in seen:
            seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def fts_query(text: str, *, limit: int = 12) -> str | None:
    """Converte texto livre numa consulta FTS5 segura (termos com prefixo, unidos por OR)."""
    terms = keywords(text, limit=limit)
    if not terms:
        return None
    return " OR ".join(f'"{term.replace(chr(34), "")}"*' for term in terms)
