"""Fase 3b: memória semântica (embeddings simulados) e coordenação multiagente."""

from __future__ import annotations

import asyncio
import json
import zlib
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import TOKEN, assert_valid_history, collect_until_done, text, tool_use
from sexta.agents.delegation import Delegator
from sexta.app import create_app
from sexta.container import build_sexta
from sexta.llm.base import Completion, LLMRequest, TextDelta, Usage
from sexta.memory.semantic import SemanticUnavailable, normalize_rows, rrf_merge
from sexta.memory.text import STOPWORDS, normalize

# --- Embeddings de mentira: "conceitos" em vez de significado real ----------------------

CONCEPTS = {"carro": "veiculo", "automovel": "veiculo", "veiculo": "veiculo", "cachorro": "cao", "cao": "cao"}


class FakeEmbedder:
    model = "fake-conceitos"

    def __init__(self):
        self.calls = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        out = np.zeros((len(texts), 96), dtype=np.float32)
        for i, value in enumerate(texts):
            for word in normalize(value).split():
                if word in STOPWORDS:
                    continue
                weight = 1.0 if word in CONCEPTS else 0.3  # o "conceito" pesa mais que o resto
                out[i, zlib.crc32(CONCEPTS.get(word, word).encode()) % 96] += weight
        return normalize_rows(out)


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def sx(settings, provider, embedder):
    instance = build_sexta(settings, provider=provider, embedder_factory=lambda: embedder)
    yield instance
    instance.close()


def test_rrf_merge_rewards_items_in_both_lists():
    scores = rrf_merge([1, 2, 3], [3, 4])
    assert max(scores, key=scores.get) == 3
    assert scores[1] > scores[4]


def test_semantic_search_finds_meaning_that_words_miss(sx):
    car, _ = sx.memory.add("Tenho um automóvel elétrico da BYD", category="perfil")
    sx.memory.add("Meu time é o Palmeiras", category="perfil")
    assert sx.memory.search("carro") == []  # só BM25 (modelo ainda não carregado)
    assert sx.semantic.status()["state"] == "off"

    sx.semantic.start(background=False)  # carrega e indexa o que já existia
    assert sx.semantic.status() == {
        "state": "ready",
        "model": "fake-conceitos",
        "indexed": 2,
        "total": 2,
        "error": None,
    }
    found = sx.memory.search("qual é o meu carro?")
    assert found and found[0].id == car.id
    assert [m.id for m in sx.memory.relevant_for("vou viajar de carro")] == [car.id]

    # Novas memórias e edições são indexadas na hora; exclusão remove o vetor
    dog, _ = sx.memory.add("O cachorro se chama Thor", category="pessoas")
    assert sx.memory.search("cão")[0].id == dog.id
    sx.memory.update(dog.id, content="A gata se chama Luna")
    assert sx.memory.search("cão") == []
    sx.memory.delete(car.id)
    assert sx.semantic.status()["indexed"] == 2
    assert sx.memory.search("carro") == []


def test_semantic_can_be_disabled_or_unavailable(settings, provider, embedder):
    instance = build_sexta(settings, provider=provider, embedder_factory=lambda: embedder)
    try:
        instance.memory.add("Tenho um automóvel elétrico")
        instance.runtime.update({"semantic_memory": False})
        instance.semantic.start(background=False)
        assert instance.semantic.status()["state"] == "disabled"
        assert instance.memory.search("carro") == []
    finally:
        instance.close()

    def broken():
        raise SemanticUnavailable("instale o pacote opcional")

    instance = build_sexta(settings, provider=provider, embedder_factory=broken)
    try:
        assert instance.semantic.status()["state"] == "disabled"  # a configuração ficou salva
        instance.runtime.update({"semantic_memory": True})
        instance.semantic.start(background=False)
        status = instance.semantic.status()
        assert status["state"] == "unavailable" and "pacote" in status["error"]
        assert [m.content for m in instance.memory.search("automóvel")] == ["Tenho um automóvel elétrico"]
    finally:
        instance.close()


def test_duplicates_and_merge(sx):
    sx.semantic.start(background=False)
    a, _ = sx.memory.add("Gosto de café sem açúcar", category="preferencias", tags=["bebida"], importance=2)
    b, _ = sx.memory.add("Gosto muito de café sem açúcar", category="preferencias", tags=["manha"], importance=4)
    sx.memory.add("Estudo engenharia de software", category="perfil")
    pairs = sx.memory.duplicates()
    assert len(pairs) == 1 and {pairs[0]["a"]["id"], pairs[0]["b"]["id"]} == {a.id, b.id}
    merged = sx.memory.merge(a.id, b.id)
    assert merged.content == a.content and merged.importance == 4 and set(merged.tags) == {"bebida", "manha"}
    assert sx.memory.get(b.id) is None and sx.memory.duplicates() == []
    with pytest.raises(ValueError):
        sx.memory.merge(a.id, a.id)


def test_memory_semantic_api(settings, provider, embedder):
    app = create_app(sexta=build_sexta(settings, provider=provider, embedder_factory=lambda: embedder))
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        assert client.get("/api/memories/semantic").json()["state"] == "off"
        assert client.get("/api/memories/duplicates").json()["available"] is False
        a = client.post("/api/memories", json={"content": "Gosto de café sem açúcar"}).json()["memory"]
        b = client.post("/api/memories", json={"content": "Gosto muito de café sem açúcar"}).json()["memory"]
        client.post("/api/memories/semantic/reindex")
        app.state.sexta.semantic.wait(5)
        assert client.get("/api/status").json()["semantic_memory"] == "ready"
        pairs = client.get("/api/memories/duplicates").json()["pairs"]
        assert len(pairs) == 1 and pairs[0]["similarity"] >= 0.9
        merged = client.post("/api/memories/merge", json={"keep_id": b["id"], "remove_id": a["id"]})
        assert merged.status_code == 200 and merged.json()["id"] == b["id"]
        assert client.post("/api/memories/merge", json={"keep_id": b["id"], "remove_id": 999}).status_code == 404


# --- Multiagente --------------------------------------------------------------------------


class RoutedProvider:
    """Responde conforme quem chama: a IA principal ou cada subagente (pelo system prompt)."""

    name = "anthropic"

    def __init__(self):
        self.requests: list[LLMRequest] = []
        self.handlers: dict[str, Any] = {}
        self.concurrent = 0
        self.max_concurrent = 0

    def who(self, request: LLMRequest) -> str:
        marker = 'Você é o agente "'
        if marker in request.system:
            return request.system.split(marker, 1)[1].split('"', 1)[0]
        return "principal"

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            await asyncio.sleep(0.02)  # dá chance aos outros subagentes de rodarem juntos
            content, stop = await self.handlers[self.who(request)](request)
        finally:
            self.concurrent -= 1
        for block in content:
            if block["type"] == "text":
                yield TextDelta(block["text"])
        yield Completion(content, stop, request.model, Usage(input_tokens=1000, output_tokens=200))


def rounds(request: LLMRequest) -> int:
    return sum(1 for m in request.messages if m["role"] == "assistant")


@pytest.fixture
def routed():
    return RoutedProvider()


@pytest.fixture
def ma(settings, routed):
    instance = build_sexta(settings, provider=routed)
    yield instance
    instance.close()


def delegate_call(tasks: list[dict[str, str]]) -> dict[str, Any]:
    return tool_use("tu_delegar", "delegate_tasks", {"tasks": tasks})


async def test_delegation_runs_subagents_in_parallel_with_their_own_tools(ma, routed):
    ma.memory.add("O usuário prefere Python", category="preferencias", pinned=True)

    async def principal(req):
        if rounds(req) == 0:
            return [
                text("Vou dividir o trabalho."),
                delegate_call(
                    [
                        {"agent": "pesquisa", "task": "Levante o que sabemos sobre as preferências do usuário."},
                        {"agent": "programacao", "task": "Esboce uma função de soma.", "context": "Use Python."},
                    ]
                ),
            ], "tool_use"
        return [text("Integrei os relatórios dos dois agentes.")], "end_turn"

    async def pesquisa(req):
        names = {t.name for t in req.tools}
        assert {"memory_search", "news_search", "web_fetch", "browser_open"} <= names
        assert not names & {"browser_click", "browser_type", "fs_write", "shell_run", "delegate_tasks"}
        if rounds(req) == 0:
            return [tool_use("tu_p1", "memory_search", {"query": "Python"})], "tool_use"
        result = req.messages[-1]["content"][0]
        assert result["tool_use_id"] == "tu_p1" and "Python" in result["content"]
        return [text("Relatório da pesquisa: o usuário prefere Python.")], "end_turn"

    async def programacao(req):
        assert "delegate_tasks" not in {t.name for t in req.tools}
        assert "Use Python." in req.messages[0]["content"][1]["text"]
        if rounds(req) == 0:  # tenta delegar de novo (recursão) e usar ferramenta fora da lista
            return [
                tool_use("tu_c1", "delegate_tasks", {"tasks": [{"agent": "geral", "task": "fazer tudo por mim"}]}),
                tool_use("tu_c2", "process_kill", {"pid": 1}),
            ], "tool_use"
        results = {r["tool_use_id"]: r for r in req.messages[-1]["content"]}
        assert results["tu_c1"]["is_error"] and "não está disponível" in results["tu_c1"]["content"]
        assert results["tu_c2"]["is_error"]
        return [text("def soma(a, b):\n    return a + b")], "end_turn"

    routed.handlers = {
        "principal": principal,
        "Pesquisa e Notícias": pesquisa,
        "Engenharia de Software": programacao,
    }
    queue = ma.bus.subscribe()
    ids = await ma.orchestrator.submit("Pesquise minhas preferências e escreva uma função de soma")
    events = await collect_until_done(queue, timeout=10)
    done = events[-1]
    assert done["status"] == "done" and "Integrei" in done["text"]
    assert routed.max_concurrent >= 2  # os dois subagentes rodaram ao mesmo tempo

    # Relatórios voltaram como resultado da ferramenta, na ordem pedida
    messages = ma.conversations.api_messages(ids["conversation_id"])
    assert_valid_history(messages)
    report = json.loads(messages[2]["content"][0]["content"])["relatorios"]
    assert [r["agente"] for r in report] == ["Pesquisa e Notícias", "Engenharia de Software"]
    assert "prefere Python" in report[0]["result"] and "def soma" in report[1]["result"]
    assert all(r["status"] == "done" and r["cost_usd"] > 0 for r in report)

    # Progresso dos subagentes vai para o cartão da ferramenta, sem cartões soltos
    sub_events = [e for e in events if e["type"] == "subagent"]
    assert {e["tool_use_id"] for e in sub_events} == {"tu_delegar"}
    assert {e["status"] for e in sub_events} >= {"queued", "thinking", "tool", "done"}
    assert not [e for e in events if e["type"] == "tool_status" and e["tool_use_id"] in {"tu_p1", "tu_c1"}]

    # Custo da tarefa inclui os subagentes; ferramentas deles foram auditadas na mesma tarefa
    record = ma.tasks.get(ids["task_id"])
    calls = ma.db.query_one("SELECT COUNT(*) AS n FROM usage_log WHERE task_id = ?", (ids["task_id"],))["n"]
    assert calls == 6  # 2 da principal + 2 de cada subagente
    assert (
        record["cost_usd"] == pytest.approx(ma.usage.task_cost(ids["task_id"]))
        and done["cost_usd"] == record["cost_usd"]
    )
    audited = ma.audit.list(limit=50)
    assert any(a["tool"] == "memory_search" and a["task_id"] == ids["task_id"] for a in audited)


async def test_subagent_actions_follow_permissions(ma, routed):
    ma.runtime.update({"permission_overrides": {"fs.write": "deny"}})

    async def principal(req):
        if rounds(req) == 0:
            return [delegate_call([{"agent": "programacao", "task": "Crie o arquivo notas.txt"}])], "tool_use"
        return [text("Não foi possível criar o arquivo.")], "end_turn"

    async def programacao(req):
        if rounds(req) == 0:
            return [tool_use("tu_w", "fs_write", {"path": "notas.txt", "content": "oi"})], "tool_use"
        result = req.messages[-1]["content"][0]
        assert result["is_error"] and "negada" in result["content"]
        return [text("A escrita foi negada pela política.")], "end_turn"

    routed.handlers = {"principal": principal, "Engenharia de Software": programacao}
    queue = ma.bus.subscribe()
    await ma.orchestrator.submit("crie notas.txt")
    events = await collect_until_done(queue, timeout=10)
    assert events[-1]["status"] == "done"
    assert not (ma.settings.workspace_dir / "notas.txt").exists()


async def test_cancel_while_subagents_run_keeps_history_valid(ma, routed):
    started = asyncio.Event()

    async def principal(req):
        return [delegate_call([{"agent": "pesquisa", "task": "Pesquisa demorada sobre IA"}])], "tool_use"

    async def slow(req):
        started.set()
        await asyncio.sleep(30)
        return [text("nunca chega")], "end_turn"

    routed.handlers = {"principal": principal, "Pesquisa e Notícias": slow}
    queue = ma.bus.subscribe()
    ids = await ma.orchestrator.submit("pesquise sobre IA com calma")
    await asyncio.wait_for(started.wait(), 5)
    ma.tasks.cancel(ids["task_id"])
    events = await collect_until_done(queue, timeout=5)
    assert events[-1]["status"] == "cancelled"
    assert_valid_history(ma.conversations.api_messages(ids["conversation_id"]))
    assert any(e["type"] == "subagent" and e["status"] == "cancelled" for e in events)


def test_allowed_tools_never_include_delegation(ma):
    delegator = Delegator(ma.orchestrator)
    from sexta.agents.registry import AGENTS

    for agent in AGENTS.values():
        allowed = delegator.allowed_tools(agent)
        assert "delegate_tasks" not in allowed and "memory_search" in allowed
        assert allowed == sorted(allowed)
