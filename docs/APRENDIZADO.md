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

## Fase 2 — conceitos usados

### 9. Processamento de sinais de áudio (DSP) básico
- Veja: `web/js/voice/clap-detector.js` e `tests/js/clap-detector.test.mjs`.
- Conceitos: amostras, RMS × pico, ruído de fundo (média móvel), detecção de *onset*,
  sinais sintéticos para testes.
- **Exercício:** mude `maxGap` para aceitar palmas mais lentas e escreva um teste com
  intervalo de 1 s.

### 10. Máquinas de estado
- Veja: `web/js/voice/voice.js` (off → idle → listening → thinking → speaking).
- **Exercício:** desenhe o diagrama de estados (incluindo a confirmação por voz) e compare
  com o código.

### 11. APIs do navegador: Web Speech, Web Audio e AudioWorklet
- Veja: `voice.js` (`SpeechRecognition`, `speechSynthesis`, `AudioWorkletNode`) e
  `clap-worklet.js`.
- **Exercício:** no console (F12) da janela, rode
  `sextaVoice.simulateSpeech("olá sexta-feira que horas são")`.

### 12. Integração com o sistema operacional
- Veja: `src/sexta/winsys.py` (registro do Windows, `pythonw`, processos desacoplados,
  instância única via `/api/health`) e `tests/test_winsys.py` (registro falso nos testes).
- **Exercício:** rode `sexta autostart status` e encontre o valor `SextaFeira` no
  Editor do Registro (`regedit`) em `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`.

### 12b. Voz local: threads, filas e modelos de fala
- Veja: `voice/engine.py` (máquina de estados no servidor, threads + `run_coroutine_threadsafe`),
  `voice/dsp.py` (detector de palmas e *endpointer* em NumPy), `voice/recognition.py`
  (Vosk com gramática restrita + faster-whisper) e `tests/test_voice_local.py` (tudo com
  microfone e modelos falsos).
- Conceitos: produtor/consumidor, *thread safety*, VAD (detecção de fala), *pre-roll*,
  por que separar “ativação barata sempre ligada” de “transcrição cara sob demanda”.
- **Exercício:** rode `sexta voz testar` com `--modelo base` e com `--modelo small` e compare
  tempo e qualidade.

## Fase 3 — conceitos usados

### 13. Consumo de APIs públicas, cache e resiliência
- Veja: `intel/http.py`, `intel/cache.py` (`fetch` com TTL e dado antigo de reserva),
  `intel/market.py`, `intel/weather.py` e `tests/test_intel.py` (internet simulada com
  `httpx.MockTransport`).
- Conceitos: TTL, *stale-while-error*, `asyncio.gather` com falhas isoladas, parsing
  seguro de XML (`defusedxml`), fuso horário de bolsa.
- **Exercício:** leia `_previous_close` em `intel/market.py` e o teste
  `test_yahoo_daily_change_uses_previous_session_not_chart_start`: explique o bug que ele
  evita. Depois adicione o ativo `GOLD` (ouro) em `ALIASES`.

### 14. Visualização de dados honesta
- Veja: `web/js/charts.js` (SVG puro: escala com marcas “redondas”, área a 10%, cursor que
  segue o mouse/teclado, tabela equivalente) e `web/js/views/world.js`.
- Conceitos: escolher a forma pelo trabalho do dado (número → cartão; tempo → linha), um
  eixo só, rótulo direto só no último ponto, acessibilidade (tabela, teclado, `aria-label`).
- **Exercício:** em `tests/js/world.test.mjs`, acrescente um caso para `niceTicks(0.012, 0.019)`.

### 15. Agendamento e tarefas em segundo plano
- Veja: `intel/scheduler.py` (`tick(now)` testável com relógio injetado), `intel/alerts.py`
  (intervalo mínimo, disparo único), `intel/briefing.py` (IA com reserva por modelo fixo).
- **Exercício:** crie um alerta “variação maior que 2%” para o Bitcoin na tela Mundo e use
  “Verificar agora”; depois encontre o registro em `alert_events`.

### 16. Sistemas multiagente
- Veja: `agents/delegation.py` (subagentes em paralelo com `asyncio.Semaphore`, lista
  fechada de ferramentas, sem recursão, cancelamento) e `tests/test_phase3b.py`
  (`RoutedProvider` responde conforme quem chama).
- Conceitos: decomposição de tarefas, paralelismo × custo, *least privilege* por agente,
  por que “ferramenta de delegação” é mais simples que um planejador separado (ADR-017).
- **Exercício:** peça no chat: *“pesquise as notícias de IA de hoje e, em paralelo, me diga
  como está o dólar”* e observe os cartões dos subagentes.

### 17. Embeddings e busca híbrida
- Veja: `memory/semantic.py` (vetores normalizados, similaridade de cosseno = produto
  escalar, RRF) e `memory/memories.py` (`search`).
- Conceitos: espaço vetorial, normalização L2, *recall* × precisão, limiar de similaridade,
  fusão por posição (RRF).
- **Exercício:** salve “tenho um automóvel elétrico” e busque “carro” na tela Memória com a
  busca por significado ligada e desligada.

### 18. Automação de navegador com segurança
- Veja: `browser/service.py` (thread dedicada, retrato da página com elementos numerados),
  `browser/guards.py` (SSRF, campos sensíveis, risco do clique) e `tests/test_browser.py`
  (site local + Chromium real).
- Conceitos: SSRF e por que bloquear a rede local, TOCTOU (o elemento mudou entre a
  aprovação e o clique), *prompt injection* vindo de páginas.
- **Exercício:** peça *“abra o site do Banco Central e me diga a meta da Selic”* e veja no
  chat quais ações precisaram de confirmação.

## Hábitos de engenharia que o projeto pratica

- Pequenas entregas funcionais (fases), cada uma testada.
- Decisões registradas (ADRs) — o “porquê” é tão importante quanto o “como”.
- Segurança e custos desde o início, não no fim.
- Código legível: nomes claros, funções pequenas, comentários explicando intenção.

## Como pedir ajuda para evoluir

Ao abrir uma nova sessão comigo, diga a fase/objetivo (ex.: “vamos começar a Fase 4: projetos”).
O arquivo `CLAUDE.md` na raiz guarda o contexto do projeto e as convenções, para eu
continuar exatamente de onde paramos.
