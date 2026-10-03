# CLAUDE.md — memória do projeto Sexta-Feira

Contexto para sessões futuras do Claude Code. Atualize ao final de cada fase.

## O projeto
Assistente pessoal de IA (inspirada na F.R.I.D.A.Y.) do usuário Feliphe. Objetivo de
longo prazo: centro de inteligência pessoal com roteamento de modelos, memória persistente,
automação segura do computador, voz, notícias/mercado e multiagentes. Construção **em
fases**, sempre funcional, segura e modular. O usuário quer aprender: explique decisões
brevemente e aponte onde estudar (`docs/APRENDIZADO.md`).

## Estado atual
- **Plataforma-alvo: somente Windows 11** (decisão do usuário). Repositório pessoal/privado.
- **Fase 1 concluída** (núcleo, memória, segurança, ferramentas, API, interface HUD, testes).
- **Fase 2 concluída** (voz no navegador, palmas, respostas faladas, iniciar com o Windows)
  + **voz local** no servidor (microfone direto, Vosk + faster-whisper + SAPI) — padrão.
- **Fase 3 concluída:** 3a informação e mercado (tela Mundo, alertas, resumos, agendador),
  3b multiagentes (`delegate_tasks`) e memória semântica (fastembed + RRF), 3c automação
  de sites (Playwright, guardas de rede).
- **Próxima: Fase 4 — projetos e aprendizado contínuo** (ver `docs/ROADMAP.md`); confirmar
  prioridade com o usuário.
- O usuário **não pode pagar créditos da API**: a IA vem da **assinatura Claude Pro** via
  Claude Code (`llm/claude_code.py`, provedor `claude-code`, padrão `SEXTA_LLM_PROVIDER=auto`).
  Testado de ponta a ponta com o CLI real (salvar memória + responder). A API paga continua
  suportada (`SEXTA_LLM_PROVIDER=api`), mas nunca deve ser escolhida automaticamente.

## Comandos
```bash
pip install -e ".[completo,dev]"   # instalar tudo (venv recomendado); extras: voz, memoria, web
pytest -q                    # testes (devem passar sempre)
ruff check src tests && ruff format src tests
node --test tests/js/*.test.mjs   # testes JS (o pytest já chama se houver Node)
sexta serve | open | stop | autostart on|off|status [--janela] | voz instalar|dispositivos|testar
sexta memoria instalar | status [--linhas N] | chave | token | doctor
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
7. **Voz:** ações críticas nunca são aprovadas por voz (só clique). Motor padrão = **local**
   (servidor, `voice_engine="local"`, configurações no banco); a interface só espelha o estado.
   No motor "navegador", preferências ficam no `localStorage` de cada janela.
8. Nunca gravar chaves/tokens em arquivos versionados (o usuário já colou uma chave no chat:
   ela vive só no `.env` local, que está no `.gitignore`).
9. **Subagentes** usam o mesmo `ToolExecutor`, lista fechada de ferramentas checada no código
   e nunca recebem `delegate_tasks` (sem recursão).
10. **Navegador:** só http(s); rede local bloqueada em toda requisição (`UrlGuard`); senhas/
    cartões nunca digitados; risco do clique pelo texto real do elemento; conferir o elemento
    antes de clicar. Testes liberam hosts locais só via `allow_hosts`.
11. Dados de mercado/notícias sempre com **fonte e horário**; estimativas marcadas; nada é
    recomendação.

## Provedor "assinatura" (Claude Code, padrão)
- `claude -p --input-format stream-json --output-format stream-json --verbose
  --include-partial-messages --no-session-persistence --safe-mode --tools "" --system-prompt-file F
  --model M [--effort E] [--fallback-model …]`, cwd `<dados>/claude-code`, env sem `ANTHROPIC_API_KEY`.
- Ferramentas no prompt; o modelo responde com `<tool_call>{"name","input"}</tool_call>` →
  `tool_use`. **Nunca ligar ferramentas nativas** (com WebSearch ligado ele tenta chamar as da
  Sexta como nativas). Lembrete `REMINDER` no fim da transcrição evita “disse que salvou”.
- Custo 0 (`UsageTracker`); uso do plano em `/api/status.plan` (chip “Plano N%”).
- Opções novas ausentes em CLIs antigos são removidas e a chamada repetida (`OPTIONAL_FLAGS`).
- Testes: `tests/test_claude_code.py` com `FakeCLI`; o fixture `settings` fixa `llm_provider="api"`.

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

## Voz e Windows (Fase 2)
- Front: `web/js/voice/` — `speech-text.js` (ativação/controle/texto falável, puro),
  `clap-detector.js` (puro) + `clap-worklet.js`, `voice.js` (controlador/estado/TTS).
  `window.sextaVoice.simulateSpeech()` permite testar sem microfone.
- Backend: `submit(channel="voz")` → contexto do turno pede resposta curta; eventos levam `channel`.
- `winsys.py`: chave `HKCU\...\Run` (valor `SextaFeira`), `pythonw -m sexta serve --app-window
  --headless --workdir <projeto>`, janela Chrome/Edge com `--user-data-dir=<data>/navegador` e
  `--autoplay-policy=no-user-gesture-required`; instância única via `/api/health`;
  `sexta stop` → `POST /api/system/shutdown`.
- Teste e2e de palmas: Chromium com `--use-file-for-fake-audio-capture=claps.wav%noloop`.

## Fase 3 — onde fica cada coisa
- `intel/`: `http.py` (cliente único, `MockTransport` nos testes), `cache.py` (`fetch` com TTL
  e dado antigo), `feeds.py`, `weather.py`, `market.py`, `service.py` (fachada), `alerts.py`,
  `briefing.py`, `scheduler.py`. Rotas em `api/intel_routes.py`; UI em `web/js/views/world.js`
  + `web/js/charts.js` (SVG puro; seguir a skill de dataviz).
- `agents/delegation.py` (`Delegator`), ferramenta em `tools/agent_tools.py`; eventos
  `subagent` aparecem no cartão do chat. Custo da tarefa = `UsageTracker.task_cost`.
- `memory/semantic.py` (`SemanticIndex`; estados off/loading/ready/unavailable/disabled);
  `build_sexta(embedder_factory=...)` injeta embedder falso nos testes.
- `browser/` (`service.py` thread dedicada, `guards.py`, `fetch.py`, `readable.py`);
  ferramentas em `tools/browser_tools.py`; `build_sexta(browser=...)` nos testes.
- `ToolOutput.images` vira bloco `image` no `tool_result`; `ToolContext.tool_use_id` é
  preenchido pelo executor.

## Armadilhas já encontradas
- Python 3.11: `asyncio.wait_for` pode engolir cancelamento se o futuro concluir junto →
  `TaskManager` mantém flag `cancel_requested` checada pelo orquestrador.
- `ruff format` pode juntar linhas; revise condições longas após formatar.
- Google Fonts pode falhar offline/atrás de proxy — a UI tem fontes de fallback.
- argparse: opção repetida no parser principal e no subparser é sobrescrita pelo default do
  subparser → usar `default=argparse.SUPPRESS` no subparser.
- `pythonw` não tem console (`sys.stdout is None`): logs vão para `<data>/logs/sexta.log`.
- Reconhecimento de fala do Chrome: sessões contínuas terminam sozinhas → reiniciar no `onend`
  com backoff; erro `audio-capture` pode ser passageiro (não bloquear de vez).
- Yahoo chart: `chartPreviousClose` com `range=5d` é de 5 dias atrás → variação diária vem do
  último pregão anterior (`_previous_close`).
- Ambiente de nuvem do Claude Code: a política de rede bloqueia as fontes externas e os
  downloads de modelos (403 no proxy) → testar com mocks; `pkill -f` pode matar o próprio shell.
- Em segundo plano (`--headless`/pythonw) stdout/stderr são redirecionados para o log
  (`_LogStream`: tqdm de downloads quebrava com `sys.stderr = None`); falhas nativas vão para
  `<dados>/logs/falhas.log` (faulthandler). Nunca imprimir o link com token em modo headless.
- Playwright no Windows precisa do loop Proactor (subprocessos) — garantido na thread do
  navegador.

## Estrutura
`src/sexta/{core,llm,memory,security,tools,agents,intel,browser,voice,api,web}` · `tests/` · `docs/`
