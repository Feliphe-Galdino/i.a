"""Texto ↔ fala: frase de ativação, comandos de controle e texto "falável".

Versão Python de ``web/js/voice/speech-text.js`` (mesmas regras, mesmos testes).
"""

from __future__ import annotations

import re
import unicodedata

_NAME_SINGLE = {"sextafeira", "6afeira", "sestafeira", "cestafeira", "sextafeiras", "sexyfeira"}
_NAME_FIRST = {"sexta", "sesta", "cesta", "6a", "6", "sexy"}
_GREET_ONE = {"ola", "oi", "ei", "hey", "alo", "opa", "eai", "fala", "hello"}
_GREET_TWO = {"e ai", "bom dia", "boa tarde", "boa noite", "ola ola"}


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def norm_word(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _strip_accents(word.lower().replace("ª", "a")))


def normalize_speech(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _strip_accents((text or "").lower().replace("ª", "a"))).strip()


def match_wake(text: str, *, name_only: bool = False) -> str | None:
    """Procura "Olá, Sexta-Feira" (e variações). Retorna o comando dito depois (pode ser "")
    ou ``None`` se não houver ativação."""
    tokens = (text or "").split()
    norm = [norm_word(t) for t in tokens]
    for i, word in enumerate(norm):
        name_end = -1
        if word in _NAME_SINGLE:
            name_end = i
        elif word in _NAME_FIRST and i + 1 < len(norm) and norm[i + 1] == "feira":
            name_end = i + 1
        if name_end < 0:
            continue
        greeted = (i > 0 and norm[i - 1] in _GREET_ONE) or (i > 1 and f"{norm[i - 2]} {norm[i - 1]}" in _GREET_TWO)
        if greeted or (name_only and i == 0):
            return re.sub(r"^[\s,.!?;:—-]+", "", " ".join(tokens[name_end + 1 :])).strip()
    return None


_CONTROL = [
    ("silence", re.compile(r"^(silencio|cala a boca|chega|para de falar|pare de falar|quieta|fica quieta|shh+)\b")),
    (
        "stop",
        re.compile(r"^(parar|pare|para tudo|interromper|interrompa|abortar|aborta|cancelar tarefa|cancela tudo)\b"),
    ),
    (
        "yes",
        re.compile(
            r"^(sim|pode|pode sim|pode fazer|confirmo|confirmar|confirmado|aprovo|aprovado|autorizo|positivo|claro|manda ver|ok pode)\b"
        ),
    ),
    ("no", re.compile(r"^(nao|negativo|nega|negar|negado|recuso|nao pode|cancela|cancelar|de jeito nenhum)\b")),
]


def match_control(text: str) -> str | None:
    """ "silence" | "stop" | "yes" | "no" | None — só para frases curtas."""
    norm = normalize_speech(text)
    if not norm or len(norm.split()) > 6:
        return None
    for kind, pattern in _CONTROL:
        if pattern.search(norm):
            return kind
    return None


def shorten_paths(text: str) -> str:
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", lambda m: [p for p in m.group(0).split("\\") if p][-1], text or "")
    return re.sub(r"(^|\s)(/[^\s\"']+)", lambda m: m.group(1) + [p for p in m.group(2).split("/") if p][-1], text)


_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


def to_speakable(markdown: str, *, max_chars: int = 600) -> str:
    text = markdown or ""
    had_code = "```" in text
    text = re.sub(r"```[\s\S]*?(```|$)", " ", text)
    text = re.sub(r"(?m)^\s*\|.*\|\s*$", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\((https?:[^)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", "link", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*(\d+)[.)]\s+", r"\1. ", text)
    text = re.sub(r"(\*\*|__|\*|_|~~)", "", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s*\n+\s*", ". ", text)
    text = re.sub(r"\.(\s*\.)+", ".", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = (cut[: end + 1] if end > max_chars * 0.4 else cut.rstrip() + "…") + " O restante está na tela."
    if had_code:
        text = f"{text} Coloquei o código na tela.".strip()
    return re.sub(r"^\.\s*", "", text)
