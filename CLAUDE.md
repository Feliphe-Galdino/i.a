# CLAUDE.md — memória do projeto Sexta-Feira

Contexto para sessões futuras do Claude Code. Atualize ao final de cada fase.

## O projeto
Assistente pessoal de IA (inspirada na F.R.I.D.A.Y.) do usuário Feliphe. Objetivo de
longo prazo: centro de inteligência pessoal com roteamento de modelos, memória persistente,
automação segura do computador, voz, notícias/mercado e multiagentes. Construção **em
fases**, sempre funcional, segura e modular. O usuário quer aprender: explique decisões
brevemente e aponte onde estudar (`docs/APRENDIZADO.md`).

## Estado atual
- **Fase 1 concluída** (núcleo, memória, segurança, ferramentas, API, interface HUD, testes).
- **Próxima: Fase 2 — voz** (ver `docs/ROADMAP.md`).

## Comandos
```bash
pip install -e ".[dev]"      # instalar (venv recomendado)
pytest -q                    # testes (devem passar sempre)
ruff check src tests && ruff format src tests
sexta serve | sexta doctor | sexta token
```

## Convenções
- Python 3.11+, FastAPI, Pydantic v2, SQLite/FTS5. Interface: HTML/CSS/JS (módulos ES), sem build.
- Identificadores em inglês; comentários, docstrings, mensagens, UI e docs em **português (pt-BR)**.
- Ruff com linha de 120. Testes com pytest-asyncio (`asyncio_mode = auto`).
- Toda funcionalidade nova vem com testes; o `ScriptedProvider` (tests/conftest.py) simula a IA.
- Dependências apontam para baixo (ver tabela em `docs/ARQUITETURA.md`); `container.py` monta tudo.
- Nova decisão arquitetural → novo ADR em `docs/ARQUITETURA.md`.

## Invariantes que NÃO podem quebrar
1. **Histórico append-only:** nunca editar/remover mensagens gravadas; system prompt congelado
   por conversa; contexto do turno (memórias, data, agente) vai na mensagem do usuário.
2. **Todo `tool_use` gravado recebe `tool_result`** (inclusive em erro, recusa, truncamento,
   cancelamento) — senão a próxima chamada à API falha.
3. **Segurança no código:** toda ferramenta passa pelo `ToolExecutor` (validação → guardas →
   política → aprovação → execução → redação de segredos → auditoria). Ações críticas sempre
   pedem confirmação. Timeout de aprovação = negar.
4. **Segredos** só no `.env`; nunca no banco, nunca para a IA, nunca em subprocessos.
5. Lista de ferramentas em ordem estável (faz parte do prefixo em cache).
6. Interface: nunca usar `innerHTML` com dados não escapados; use `h()`/`add()`/`fill()` de
   `web/js/ui.js` (o `Element.append` nativo transforma arrays/null em texto).

## Integração com a API do Claude (estado em 2026-10)
- Modelos: `claude-haiku-4-5` (rápido; sem `effort`/thinking), `claude-sonnet-5-5`,
  `claude-opus-5-5` (thinking adaptativo sempre ligado; controle por `output_config.effort`,
  padrão `medium` no Opus 5.5; `tool_choice` forçado dá 400; sem prefill).
- Usamos `client.beta.messages.stream` com: `thinking: {type: adaptive, display: summarized,
  block_binding: {prefix_mismatch_behavior: drop_block}}` (beta `thinking-binding-controls-2026-08-01`),
  `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`), cache no system + automático,
  `eager_input_streaming` nas ferramentas, web search `web_search_20260209` (Haiku: `_20250305`).
- O provedor desliga recursos beta rejeitados e repete; assinatura de thinking inválida →
  remove blocos de thinking e repete uma vez.

## Armadilhas já encontradas
- Python 3.11: `asyncio.wait_for` pode engolir cancelamento se o futuro concluir junto →
  `TaskManager` mantém flag `cancel_requested` checada pelo orquestrador.
- `ruff format` pode juntar linhas; revise condições longas após formatar.
- Google Fonts pode falhar offline/atrás de proxy — a UI tem fontes de fallback.

## Estrutura
`src/sexta/{core,llm,memory,security,tools,agents,api,web}` · `tests/` · `docs/`
