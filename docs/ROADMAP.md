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
- [x] Testes automatizados (hoje 185+, incluindo navegador real e testes JS)

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

### ✅ Voz local (concluída)

- [x] Microfone direto no PC (sounddevice), funcionando **sem janela aberta**
- [x] Palavra de ativação offline (Vosk, gramática restrita) e palmas no servidor
- [x] Transcrição offline com **faster-whisper** (modelos base → large-v3-turbo)
- [x] Fala com as vozes do Windows (SAPI), alertas e resumos falados
- [x] `sexta voz instalar / dispositivos / testar`; motor “Navegador” mantido como alternativa

## ✅ Fase 3 — Inteligência ampliada, informação e automação (concluída)

**3a · Informação e mercado**
- [x] Notícias por tema (RSS de G1, Agência Brasil, BBC, InfoMoney, Tecnoblog…), busca no
      Google Notícias e tendências do Google Trends
- [x] Clima (Open-Meteo) com previsão de 7 dias e avisos estimados
- [x] Cotações (B3, EUA, índices, moedas, cripto), histórico com estatísticas e indicadores
      oficiais do Banco Central (SGS)
- [x] Cache com fonte e horário, e uso de dados antigos quando a fonte cai
- [x] Alertas (preço, variação, notícia, clima) e **resumo do dia** agendado
- [x] Tela **Mundo** com gráficos (minilinhas e histórico com cursor e tabela)

**3b · Multiagentes e memória semântica**
- [x] `delegate_tasks`: subagentes em paralelo, ferramentas por agente, mesmas permissões,
      sem recursão, custos na tarefa de origem, progresso ao vivo no chat
- [x] Embeddings locais (fastembed, multilíngue) + busca híbrida BM25 × cosseno (RRF)
- [x] Memórias parecidas: detecção e mescla com confirmação

**3c · Automação de sites**
- [x] Navegador próprio (Playwright + Edge), páginas como elementos numerados
- [x] Abrir, ler, clicar, digitar, escolher, rolar, voltar, capturar a tela; `web_fetch`
- [x] Guardas: rede local bloqueada, senhas/cartões nunca digitados, cliques críticos sempre
      confirmados, conferência do elemento antes do clique

## Fase 4 — Projetos e aprendizado contínuo

- **Projetos:** contexto, arquivos, decisões e memória por projeto; compactação de
  conversas longas.
- **Aprendizado de preferências:** feedback 👍/👎 ajusta o roteamento e o estilo.
- Consolidação automática sugerida (resumir memórias antigas de um mesmo tema).
- Classificador de roteamento com IA para pedidos ambíguos.
- Planejador explícito (plano revisável antes de executar tarefas longas).

## Fase 5 — Automação avançada e integrações

- Rotinas/macros reutilizáveis (“toda sexta às 18h, faça backup de…”), reaproveitando o
  agendador da Fase 3.
- Monitoramento de processos e alertas de recursos do PC.
- Integrações via **MCP** (Model Context Protocol): Google Calendar, e-mail, GitHub,
  Notion, casa inteligente.
- Fontes oficiais extras: INMET/Defesa Civil (alertas de clima), IBGE.
- Vozes neurais locais (Piper) e palavra de ativação treinada (openWakeWord).

## Fase 6 — Multiplataforma

- App desktop (Tauri) com ícone na bandeja e atalho global.
- Acesso pelo celular com segurança (túnel autenticado/VPN), notificações push.
- Modelos locais (Ollama) para tarefas privadas/offline como provedor adicional.

## Melhorias contínuas

- Otimização de custos (medir cache, ajustar esforço por agente).
- Mais testes de ponta a ponta da interface.
- Backup automático do banco.
