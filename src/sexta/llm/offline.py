"""Provedor offline: mantém a Sexta-Feira utilizável sem chave de API.

Permite testar a interface, a memória e as permissões antes de configurar a IA.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .base import Completion, LLMEvent, LLMRequest, TextDelta, Usage

OFFLINE_MESSAGE = (
    "Estou em **modo offline**: nenhuma chave de API foi configurada.\n\n"
    "Para me ativar por completo:\n"
    "1. Crie uma chave em https://console.anthropic.com/settings/keys\n"
    "2. Copie `.env.example` para `.env` e preencha `ANTHROPIC_API_KEY`\n"
    "3. Reinicie o servidor (`sexta serve`)\n\n"
    "Enquanto isso, a interface, a memória, o histórico e as configurações já funcionam."
)


class OfflineProvider:
    name = "offline"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        for word in OFFLINE_MESSAGE.split(" "):
            yield TextDelta(word + " ")
            await asyncio.sleep(0)
        yield Completion(
            content=[{"type": "text", "text": OFFLINE_MESSAGE}],
            stop_reason="end_turn",
            model="offline",
            usage=Usage(),
        )
