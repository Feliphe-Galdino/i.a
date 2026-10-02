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

## ✅ Fase 2 — Voz e presença (concluída)

- [x] Plataforma-alvo: **Windows 11**
- [x] Inicia com o Windows (chave `Run` do usuário, sem administrador) e abre a janela de voz
- [x] Servidor oculto (`pythonw`), instância única, logs em arquivo, `sexta open/stop/autostart`
- [x] Ativação por **“Olá, Sexta-Feira”** (Web Speech API, pt-BR) e por **duas palmas**
      (detector local em AudioWorklet, sensibilidade ajustável com medidor ao vivo)
- [x] Respostas faladas (speechSynthesis — vozes gratuitas do Windows/Chrome/Edge)
- [x] Modos Texto / Voz / Ambos; comandos “silêncio” e “parar”
- [x] Confirmação por voz para ações não críticas; críticas exigem clique
- [x] O núcleo sabe quando o pedido veio por voz e responde de forma curta e falável

**Melhorias futuras de voz:** reconhecimento local e offline (faster-whisper) e palavra de
ativação local (openWakeWord) para privacidade total; vozes neurais locais (Piper).

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
