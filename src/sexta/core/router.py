"""Roteador de modelos (o "MEGABRAIN" decide quem pensa em cada pedido).

Estratégia em camadas, 100% local e explicável (sem gastar tokens para decidir):

1. **Escolha manual** (``/rapido``, ``/equilibrado``, ``/profundo`` ou seletor da UI).
2. **Complexidade** estimada por sinais do texto (tamanho, código, verbos de
   engenharia, várias etapas) → camada base.
3. **Agente**: alguns exigem camada mínima (programação, finanças).
4. **Prioridade do usuário**: qualidade (+1), equilíbrio (0), economia (−1).
5. **Continuidade**: respostas curtas a uma conversa profunda mantêm a camada
   (preserva contexto e cache).
6. **Urgência**: reduz o *esforço* de raciocínio para responder mais rápido.
7. **Contexto longo**: troca para um modelo com janela maior se preciso.
8. **Orçamento**: perto do limite diário, limita a camada (ou bloqueia).

Cada regra aplicada vira um "motivo" exibido na interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..agents.registry import AgentProfile
from ..llm.catalog import Tier, get_model, shift_effort
from ..memory.text import strip_accents

MANUAL_PREFIX = re.compile(r"^\s*/(rapido|rápido|equilibrado|profundo)\b\s*", re.IGNORECASE)

_DEEP_HINTS = [
    "arquitetura",
    "refator",
    "otimiz",
    "depur",
    "debug",
    "implement",
    "algoritmo",
    "projete",
    "projetar",
    "escalab",
    "concorrenc",
    "paraleliz",
    "migrar",
    "migracao",
    "estrategia",
    "trade-off",
    "tradeoff",
    "analise profunda",
    "analise detalhada",
    "compare",
    "comparar",
    "prove",
    "demonstre",
    "seguranca da aplicacao",
    "modelagem",
    "performance",
    "desempenho",
    "complex",
    "sistema completo",
    "do zero",
    "end-to-end",
]
_CODE_HINTS = [
    "codigo",
    "python",
    "javascript",
    "typescript",
    "sql",
    "api",
    "funcao",
    "classe",
    "bug",
    "erro",
    "exception",
    "traceback",
    "script",
    "docker",
    "git",
    "compil",
    "framework",
    "backend",
    "frontend",
    "regex",
]
_STEP_HINTS = ["passo a passo", "etapas", "primeiro", "em seguida", "depois disso", "por fim", "plano", "roteiro"]
_SIMPLE_PATTERNS = re.compile(
    r"^(oi|ola|olá|bom dia|boa tarde|boa noite|e ai|eai|obrigad[oa]|valeu|tudo bem|blz|ok|beleza|"
    r"que horas|qual (a|e a) data|quem e voce|teste)\b",
    re.IGNORECASE,
)
_URGENT = re.compile(r"\b(urgente|urgencia|rapido|depressa|agora mesmo|asap|emergencia)\b")
_CODE_SYNTAX = re.compile(
    r"```|\bdef \w+\(|\bclass \w+|function\s*\w*\(|=>|\bimport \w+|#include|;\s*$|\{\s*$", re.MULTILINE
)


@dataclass
class RouteDecision:
    tier: Tier
    model: str
    effort: str | None
    agent_id: str
    agent_name: str
    complexity: int
    reasons: list[str] = field(default_factory=list)
    blocked: bool = False

    def public(self) -> dict:
        spec = get_model(self.model)
        return {
            "tier": self.tier.value,
            "tier_label": self.tier.label,
            "model": self.model,
            "model_label": spec.label,
            "effort": self.effort,
            "agent": self.agent_id,
            "agent_name": self.agent_name,
            "complexity": self.complexity,
            "reasons": self.reasons,
            "blocked": self.blocked,
        }


def strip_manual_prefix(text: str) -> tuple[str, Tier | None]:
    match = MANUAL_PREFIX.match(text)
    if not match:
        return text, None
    value = strip_accents(match.group(1).lower())
    return text[match.end() :], Tier(value)


def estimate_complexity(text: str) -> tuple[int, list[str]]:
    """Pontuação 0–10 com os sinais encontrados."""
    normalized = strip_accents(text.lower())
    score = 0
    signals: list[str] = []
    length = len(text)
    if length > 1500:
        score += 3
        signals.append("pedido longo")
    elif length > 400:
        score += 2
        signals.append("pedido detalhado")
    elif length > 150:
        score += 1
    if _CODE_SYNTAX.search(text):
        score += 3
        signals.append("contém código")
    if any(h in normalized for h in _CODE_HINTS):
        score += 2
        signals.append("tema de programação")
    deep = sum(1 for h in _DEEP_HINTS if h in normalized)
    if deep:
        score += min(4, deep * 2)
        signals.append("exige análise/engenharia")
    steps = sum(1 for h in _STEP_HINTS if h in normalized) + len(re.findall(r"(?m)^\s*\d+[.)]\s", text))
    if steps >= 2:
        score += 2
        signals.append("várias etapas")
    elif steps == 1:
        score += 1
    if length < 80 and _SIMPLE_PATTERNS.match(normalized.strip()):
        score = 0
        signals = ["mensagem simples"]
    return max(0, min(10, score)), signals


def tier_for(complexity: int) -> Tier:
    if complexity <= 2:
        return Tier.FAST
    if complexity <= 5:
        return Tier.BALANCED
    return Tier.DEEP


def base_effort(tier: Tier, complexity: int) -> str | None:
    if tier == Tier.FAST:
        return None
    if tier == Tier.BALANCED:
        return "low" if complexity <= 3 else "medium"
    return "high" if complexity >= 8 else "medium"


class Router:
    def __init__(self, tier_models: dict[Tier, str]):
        self.tier_models = tier_models

    def model_for(self, tier: Tier, overrides: dict[str, str] | None = None) -> str:
        if overrides and overrides.get(tier.value):
            return overrides[tier.value]
        return self.tier_models[tier]

    def decide(
        self,
        text: str,
        *,
        agent: AgentProfile,
        manual: Tier | None = None,
        previous_tier: Tier | None = None,
        priority: str = "equilibrio",
        history_tokens: int = 0,
        spent_today: float = 0.0,
        daily_budget: float = 0.0,
        budget_hard_stop: bool = False,
        tier_overrides: dict[str, str] | None = None,
    ) -> RouteDecision:
        complexity, signals = estimate_complexity(text)
        trivial = signals == ["mensagem simples"]
        reasons: list[str] = []

        if manual is not None:
            tier = manual
            reasons.append(f"escolha manual: {tier.label}")
        else:
            tier = tier_for(complexity)
            reasons.append(f"complexidade {complexity}/10" + (f" ({', '.join(signals)})" if signals else ""))

            if agent.min_tier and tier.rank < agent.min_tier.rank and not trivial:
                tier = agent.min_tier
                reasons.append(f"agente {agent.name} pede no mínimo {tier.label}")

            if priority == "qualidade" and not trivial and tier != Tier.DEEP:
                tier = tier.shift(+1)
                reasons.append("prioridade: qualidade")
            elif priority == "economia" and tier != Tier.FAST and complexity < 8:
                tier = tier.shift(-1)
                reasons.append("prioridade: economia")

            if previous_tier is not None and previous_tier.rank > tier.rank and len(text) < 200 and not trivial:
                tier = previous_tier
                reasons.append("continuidade da conversa")

        effort = base_effort(tier, complexity)
        if priority == "qualidade" and effort:
            effort = shift_effort(effort, +1)
        if _URGENT.search(strip_accents(text.lower())) and effort:
            effort = shift_effort(effort, -1)
            reasons.append("urgência: prioriza velocidade")

        model = self.model_for(tier, tier_overrides)

        # Contexto longo: garante janela suficiente.
        if history_tokens > get_model(model).context_tokens * 0.8:
            for candidate in (Tier.BALANCED, Tier.DEEP):
                if candidate.rank > tier.rank:
                    alt = self.model_for(candidate, tier_overrides)
                    if get_model(alt).context_tokens > history_tokens * 1.25:
                        tier, model = candidate, alt
                        effort = effort or base_effort(tier, complexity)
                        reasons.append("conversa longa: modelo com mais contexto")
                        break

        blocked = False
        if daily_budget > 0 and manual is None:
            ratio = spent_today / daily_budget
            if ratio >= 1:
                if budget_hard_stop:
                    blocked = True
                    reasons.append("orçamento diário esgotado")
                elif tier != Tier.FAST:
                    tier, model, effort = Tier.FAST, self.model_for(Tier.FAST, tier_overrides), None
                    reasons.append("orçamento diário esgotado: modo econômico")
            elif ratio >= 0.8 and tier == Tier.DEEP:
                tier = Tier.BALANCED
                model = self.model_for(tier, tier_overrides)
                effort = base_effort(tier, complexity)
                reasons.append("orçamento acima de 80%: limitando a Equilibrado")

        if not get_model(model).supports_effort:
            effort = None

        return RouteDecision(
            tier=tier,
            model=model,
            effort=effort,
            agent_id=agent.id,
            agent_name=agent.name,
            complexity=complexity,
            reasons=reasons,
            blocked=blocked,
        )
