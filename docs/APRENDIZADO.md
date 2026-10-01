# Guia de aprendizado — evoluindo junto com a Sexta-Feira

Este projeto é também uma escola. Cada fase usa conceitos que aparecem em sistemas
profissionais. Abaixo, o que estudar, **onde ver no código** e um exercício para fixar.

## Fase 1 — conceitos usados

### 1. Programação assíncrona (`async`/`await`)
Permite responder em streaming, rodar várias tarefas e esperar aprovações sem travar.
- Veja: `src/sexta/core/orchestrator.py` (`_run_locked`), `core/events.py` (filas).
- Conceitos: corrotinas, `asyncio.Task`, cancelamento, `Lock`, `Queue`, `wait_for`.
- **Exercício:** em `tests/test_orchestrator.py`, leia
  `test_two_messages_same_conversation_are_serialized` e explique por que as respostas
  saem em ordem.

### 2. APIs web (REST + WebSocket) com FastAPI
- Veja: `api/routes.py` (REST), `api/ws.py` (tempo real), `api/deps.py` (autenticação).
- Conceitos: rotas, validação com Pydantic, injeção de dependências, códigos HTTP.
- **Exercício:** crie a rota `GET /api/memories/random` que devolve uma memória aleatória
  (e um teste em `tests/test_api.py`).

### 3. Banco de dados e busca textual
- Veja: `memory/db.py` (migrações, triggers FTS5), `memory/memories.py` (BM25 + importância).
- Conceitos: SQL, índices, transações, busca full-text, migrações versionadas.
- **Exercício:** adicione uma migração v2 com a coluna `expires_at` em `memories`
  (memórias temporárias) — sem editar a migração v1.

### 4. Integração com modelos de IA
- Veja: `llm/anthropic_provider.py`, `llm/catalog.py`, `core/prompts.py`.
- Conceitos: tokens, streaming, *tool use*, raciocínio adaptativo e `effort`, cache de
  prompt, custo por modelo, recusas e fallback.
- **Exercício:** no painel, observe o custo de duas perguntas seguidas na mesma conversa.
  Por que a segunda tende a ler tokens do cache? (Dica: ADR-004 em `ARQUITETURA.md`.)

### 5. Roteamento e decisões explicáveis
- Veja: `core/router.py` e `tests/test_router.py`.
- **Exercício:** adicione a palavra “kubernetes” aos sinais de complexidade e escreva o
  teste que prova que “configure meu cluster kubernetes” vai para a camada Equilibrada.

### 6. Segurança de sistemas com IA
- Veja: `security/` inteiro e `docs/SEGURANCA.md`.
- Conceitos: menor privilégio, *defense in depth*, sandbox, *prompt injection*,
  auditoria, falha segura (timeout = negar).
- **Exercício:** adicione `shutdown /s` à lista de testes de comandos críticos em
  `tests/test_security.py` e confira se já é detectado.

### 7. Testes automatizados
- Veja: `tests/conftest.py` — o `ScriptedProvider` simula a IA para testar o fluxo inteiro
  sem gastar com API.
- **Exercício:** escreva um teste em que a IA chama `fs_read` num arquivo que não existe e
  verifique que o resultado volta com `is_error`.

### 8. Front-end sem framework
- Veja: `web/js/ui.js` (função `h` — cria elementos sem `innerHTML`, evitando XSS),
  `web/js/markdown.js` (escapar antes de formatar), `web/js/views/chat.js` (eventos ao vivo).
- **Exercício:** adicione um botão “copiar resposta” no rodapé de cada mensagem.

## Hábitos de engenharia que o projeto pratica

- Pequenas entregas funcionais (fases), cada uma testada.
- Decisões registradas (ADRs) — o “porquê” é tão importante quanto o “como”.
- Segurança e custos desde o início, não no fim.
- Código legível: nomes claros, funções pequenas, comentários explicando intenção.

## Como pedir ajuda para evoluir

Ao abrir uma nova sessão comigo, diga a fase/objetivo (ex.: “vamos começar a Fase 2: voz”).
O arquivo `CLAUDE.md` na raiz guarda o contexto do projeto e as convenções, para eu
continuar exatamente de onde paramos.
