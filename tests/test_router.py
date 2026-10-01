from sexta.agents.registry import AGENTS, select_agent
from sexta.core.router import Router, estimate_complexity, strip_manual_prefix
from sexta.llm.catalog import Tier

ROUTER = Router({Tier.FAST: "claude-haiku-4-5", Tier.BALANCED: "claude-sonnet-5-5", Tier.DEEP: "claude-opus-5-5"})


def decide(text: str, **kwargs):
    agent = kwargs.pop("agent", None) or select_agent(text)[0]
    return ROUTER.decide(text, agent=agent, **kwargs)


def test_greeting_goes_to_fast_model():
    decision = decide("Oi, bom dia!")
    assert decision.tier == Tier.FAST
    assert decision.model == "claude-haiku-4-5"
    assert decision.effort is None  # Haiku não usa effort
    assert decision.complexity == 0


def test_complex_programming_goes_to_opus():
    text = (
        "Preciso refatorar a arquitetura do meu backend em Python: separar a API em camadas, "
        "otimizar as consultas SQL e implementar cache. Faça passo a passo:\n"
        "1. analise o código atual\n2. proponha a nova estrutura\n3. implemente\n"
        "```python\ndef handler(req):\n    return db.query(req)\n```"
    )
    decision = decide(text)
    assert decision.agent_id == "programacao"
    assert decision.tier == Tier.DEEP
    assert decision.model == "claude-opus-5-5"
    assert decision.effort == "high"


def test_programming_agent_has_minimum_tier():
    decision = decide("tenho um bug no meu script")
    assert decision.agent_id == "programacao"
    assert decision.tier.rank >= Tier.BALANCED.rank


def test_manual_prefix_overrides_everything():
    text, manual = strip_manual_prefix("/profundo oi")
    assert text == "oi" and manual == Tier.DEEP
    decision = decide(text, manual=manual)
    assert decision.model == "claude-opus-5-5"
    assert "escolha manual" in decision.reasons[0]


def test_economy_priority_lowers_tier():
    text = "Explique a diferença entre listas e tuplas em Python com exemplos de código"
    normal = decide(text)
    economy = decide(text, priority="economia")
    assert economy.tier.rank < normal.tier.rank


def test_quality_priority_raises_tier_and_effort():
    text = "Compare duas estratégias de cache para uma API"
    normal = decide(text)
    quality = decide(text, priority="qualidade")
    assert quality.tier.rank >= normal.tier.rank
    assert quality.tier == Tier.DEEP


def test_short_follow_up_keeps_previous_tier():
    decision = decide("e se usar uma fila?", previous_tier=Tier.DEEP)
    assert decision.tier == Tier.DEEP
    assert "continuidade da conversa" in decision.reasons


def test_urgency_lowers_effort():
    calm = decide("Analise a arquitetura deste sistema e compare alternativas de escalabilidade")
    urgent = decide("Urgente: analise a arquitetura deste sistema e compare alternativas de escalabilidade")
    order = ["low", "medium", "high", "xhigh"]
    assert order.index(urgent.effort) < order.index(calm.effort)


def test_budget_exhausted_falls_back_to_fast():
    decision = decide("Refatore a arquitetura completa do sistema", spent_today=6.0, daily_budget=5.0)
    assert decision.tier == Tier.FAST
    assert not decision.blocked


def test_budget_hard_stop_blocks():
    decision = decide("Oi", spent_today=6.0, daily_budget=5.0, budget_hard_stop=True)
    assert decision.blocked


def test_budget_near_limit_caps_deep():
    decision = decide("Refatore a arquitetura e otimize o algoritmo de busca", spent_today=4.5, daily_budget=5.0)
    assert decision.tier == Tier.BALANCED


def test_long_history_moves_to_bigger_context():
    decision = decide("ok, e agora?", manual=Tier.FAST, history_tokens=190_000)
    assert decision.model != "claude-haiku-4-5"


def test_tier_model_overrides():
    decision = decide("oi", tier_overrides={"rapido": "claude-sonnet-5-5"})
    assert decision.model == "claude-sonnet-5-5"


def test_agent_selection():
    assert select_agent("qual a cotação do dólar e do bitcoin hoje?")[0].id == "financas"
    assert select_agent("organize minha rotina de estudos da semana")[0].id == "organizacao"
    assert select_agent("meu PC está lento, tem processo estranho usando a CPU")[0].id == "seguranca"
    assert select_agent("conte uma piada")[0].id == "geral"
    assert set(AGENTS) >= {"geral", "programacao", "pesquisa", "financas", "automacao", "organizacao", "seguranca"}


def test_complexity_signals_are_explained():
    score, signals = estimate_complexity("```js\nconst x = () => 1;\n```")
    assert score >= 3
    assert "contém código" in signals


def test_budget_hard_stop_applies_to_manual_choice():
    decision = decide("oi", manual=Tier.DEEP, spent_today=6.0, daily_budget=5.0, budget_hard_stop=True)
    assert decision.blocked


def test_manual_choice_skips_soft_budget_caps():
    decision = decide("oi", manual=Tier.DEEP, spent_today=6.0, daily_budget=5.0)
    assert decision.model == "claude-opus-5-5" and not decision.blocked
