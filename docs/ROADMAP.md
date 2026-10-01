# Roadmap

Construção em fases: cada uma entrega algo **utilizável** sem reconstruir o que já existe.

## ✅ Fase 1 — Fundação (concluída)

- [x] Arquitetura modular (núcleo, provedores, memória, segurança, ferramentas, API, UI)
- [x] MEGABRAIN: roteamento Haiku 4.5 / Sonnet 5.5 / Opus 5.5 com motivos explicáveis
- [x] Agentes especializados selecionados automaticamente
- [x] Memória persistente com busca, categorias, fixação, exportação/importação
- [x] Histórico pesquisável de conversas e atividades
- [x] Ferramentas: arquivos, terminal, processos, programas, memória, histórico
- [x] Permissões, autonomia, confirmações, guardas, auditoria, orçamento, botão PARAR
- [x] Interface HUD: chat em tempo real, painel, memória, atividade, configurações
- [x] Pesquisa na web integrada (servidor da Anthropic)
- [x] 105+ testes automatizados

## 🔜 Fase 2 — Voz e presença

**Objetivo:** falar com a Sexta-Feira sem tocar no teclado.

- Reconhecimento de fala (pt-BR): navegador (Web Speech API) para começar; depois
  **Whisper/faster-whisper local** (privacidade, offline).
- Palavra de ativação **“Olá, Sexta-Feira”**: detecção local (openWakeWord/Porcupine) —
  o áudio não sai do computador até a ativação.
- **Duas palmas**: detector de picos de energia no microfone (Web Audio/`sounddevice`),
  com sensibilidade ajustável e janela de 150–700 ms entre as palmas.
- Respostas faladas com voz personalizável (TTS do sistema → Piper local → vozes neurais).
- Modos: texto, voz ou ambos; indicador de microfone e configurações de privacidade.
- Respostas mais curtas quando a interação for por voz.

## Fase 3 — Inteligência ampliada

- **Planejador multiagente:** decompõe pedidos complexos, executa agentes em paralelo e
  consolida a resposta.
- **Memória semântica:** embeddings (sqlite-vec) + BM25 híbrido; consolidação automática
  (resumir/mesclar memórias parecidas).
- **Projetos:** contexto, arquivos, decisões e memória por projeto; compactação de
  conversas longas.
- **Aprendizado de preferências:** feedback 👍/👎 ajusta o roteamento e o estilo.
- Classificador de roteamento com IA para pedidos ambíguos.

## Fase 4 — Informação e mercado

- Notícias nacionais e internacionais (RSS/APIs oficiais) com resumo e fontes.
- Indicadores econômicos (Banco Central/SGS, IBGE), câmbio, Selic, IPCA.
- Ações, FIIs, cripto (APIs de mercado) com gráficos no painel.
- Clima e alertas (Open-Meteo, INMET/Defesa Civil).
- Alertas personalizados e **resumos periódicos** (agendador).
- Regras: fonte e horário em cada dado; fatos × estimativas × opiniões; previsões nunca são
  garantias.

## Fase 5 — Automação avançada

- Navegação web automatizada (Playwright) com confirmações por etapa.
- Rotinas/macros reutilizáveis (“toda sexta às 18h, faça backup de…”).
- Monitoramento de processos e alertas de recursos.
- Integrações via **MCP** (Model Context Protocol): Google Calendar, e-mail, GitHub,
  Notion, casa inteligente.

## Fase 6 — Multiplataforma

- App desktop (Tauri) com ícone na bandeja e atalho global.
- Acesso pelo celular com segurança (túnel autenticado/VPN), notificações push.
- Modelos locais (Ollama) para tarefas privadas/offline como provedor adicional.

## Melhorias contínuas

- Otimização de custos (medir cache, ajustar esforço por agente).
- Mais testes de ponta a ponta da interface.
- Backup automático do banco.
