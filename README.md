# SEXTA-FEIRA — sua assistente pessoal de IA

> Inspirada na F.R.I.D.A.Y. do Homem de Ferro: um centro de inteligência digital que
> conversa, programa, pesquisa, acompanha notícias e mercado, usa sites, coordena agentes,
> automatiza o computador e **aprende com você**. Liga junto com o Windows e atende a
> **duas palmas** ou a um **“Olá, Sexta-Feira”** — direto pelo microfone do PC.

**Plataforma:** Windows 11 · **Status:** Fase 3 concluída (informação e mercado,
multiagentes, memória semântica e automação de sites). Veja o [roadmap](docs/ROADMAP.md).

---

## O que ela já faz

| Módulo | O que faz |
|---|---|
| **Voz local** | Escuta o **microfone do PC** mesmo sem janela aberta: ativação por **“Olá, Sexta-Feira”** ou **duas palmas**, transcrição **offline** (Whisper) e resposta com a **voz do Windows**. “Silêncio”, “parar”, “sim/não” para confirmações não críticas. |
| **Inicia com o Windows** | Sobe oculto ao entrar no Windows, já escutando — sem administrador. |
| **MEGABRAIN** | Escolhe o modelo ideal: **Haiku 4.5** (rápido/barato), **Sonnet 5.5** (equilibrado) ou **Opus 5.5** (programação e análises complexas), e o nível de raciocínio — explicando cada decisão. |
| **Multiagentes** | Para trabalhos grandes, divide em subtarefas e coloca **agentes especializados em paralelo** (programação, pesquisa, finanças, automação, organização, segurança), cada um com suas ferramentas, e integra os relatórios. |
| **Memória** | Aprende fatos, preferências, projetos e correções; busca por **palavras e por significado** (embeddings no seu PC); encontra memórias repetidas para mesclar; você vê, edita, fixa, exporta e apaga tudo. |
| **Mundo** | Notícias (G1, Agência Brasil, BBC, InfoMoney, Tecnoblog…), tendências, **clima** com avisos, **cotações** (B3, EUA, moedas, cripto) com gráficos, **indicadores do Banco Central**, **alertas** personalizados e **resumo do dia** automático — sempre com fonte e horário. |
| **Sites** | Abre e usa sites num navegador próprio (Edge): lê, clica, preenche e busca. **Nunca digita senhas**; compras, envios e exclusões **sempre** pedem sua confirmação. |
| **Controle do PC** | Arquivos, terminal, processos, programas e links — sempre dentro das permissões. |
| **Segurança** | Níveis de autonomia, confirmações, guardas no código, pastas liberadas, lixeira, auditoria, orçamento diário e botão **PARAR**. |
| **Interface** | HUD futurista: chat em tempo real, painel, **Mundo**, memória, atividade e configurações. |

## Instalação (Windows 11)

### 1. Pré-requisitos

- **Python 3.11+** — https://www.python.org/downloads/ (marque **“Add Python to PATH”**).
- **Git** — https://git-scm.com/download/win
- **Assinatura Claude Pro (ou Max) + Claude Code** — a IA usa o seu plano, **sem custo extra**:
  no PowerShell, instale com `irm https://claude.ai/install.ps1 | iex` e rode `claude` **uma vez**
  para entrar com a sua conta (depois pode fechar). Não precisa de créditos da API.
- **Voz em português no Windows** (para ela falar em pt-BR): Configurações → Hora e idioma →
  Fala → *Adicionar vozes* → **Português (Brasil)**.

### 2. Instalar

No **PowerShell**:

```powershell
cd $HOME
git clone https://github.com/feliphe-galdino/i.a.git
cd i.a
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # se bloquear: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[completo]"             # núcleo + voz local + memória semântica + automação de sites
sexta voz instalar                       # baixa os modelos de voz (~500 MB, uma vez)
sexta memoria instalar                   # baixa o modelo de busca por significado (~220 MB, uma vez)
sexta doctor                             # verifica se está tudo certo
```

> Quer algo mais leve? `pip install -e .` instala só o núcleo; os extras são
> `[voz]`, `[memoria]` e `[web]` (ou `[completo]` para todos).

### 3. Testar a voz

```powershell
sexta voz dispositivos     # lista os microfones
sexta voz testar           # grava 5 s, transcreve e repete em voz alta
```

### 4. Usar e deixar ligada com o Windows

```powershell
sexta autostart on         # inicia oculto com o Windows, já escutando o microfone
sexta open                 # abre a interface quando quiser ver o HUD
```

Pronto: ao entrar no Windows, bata **duas palmas** ou diga **“Olá, Sexta-Feira”** →
um bipe indica que ela está ouvindo → faça o pedido. Prefere que a janela também abra
sozinha? `sexta autostart on --janela`.

## Comandos

| Comando | O que faz |
|---|---|
| `sexta open` | Abre a interface (sobe o servidor em segundo plano se preciso) |
| `sexta serve` | Roda o servidor neste terminal (útil para ver mensagens) |
| `sexta stop` | Encerra o servidor que está em segundo plano |
| `sexta autostart on` / `off` / `status` | Iniciar com o Windows (`--janela` abre a interface também) |
| `sexta voz instalar` / `dispositivos` / `testar` | Voz local: modelos, microfones, teste |
| `sexta memoria instalar` | Modelo da busca por significado + indexação das memórias |
| `sexta status` | Diz se o servidor está rodando e mostra as últimas linhas do log (e falhas graves) |
| `sexta chave` | Opcional: salva uma chave da API (créditos) no `.env` — só se um dia quiser usar a API paga |
| `sexta token` | Mostra o token de acesso (a “senha” da interface) |
| `sexta doctor` | Diagnóstico da instalação |

## Usando a voz

| Você diz / faz | Ela faz |
|---|---|
| 👏👏 ou “Olá, Sexta-Feira” | Bipe e começa a ouvir |
| “Olá, Sexta-Feira, como está o dólar hoje?” | Ativa e já executa o pedido |
| “Silêncio” (ou 👏👏 enquanto fala) | Para de falar |
| “Parar” | Interrompe as tarefas em andamento |
| “Sim” / “Não” | Responde a confirmações (só ações **não críticas**; críticas exigem clique) |

**Modos:** *Ambos* (fala as respostas dos pedidos falados — padrão) ou *Voz* (fala todas).
Ajuste microfone, sensibilidade das palmas (com medidor ao vivo), voz do Windows, velocidade
e modelo de transcrição em **Configurações → Voz e ativação**. Alertas e resumos do dia
também podem ser falados.

**Privacidade:** palmas, palavra de ativação e transcrição rodam **no seu computador** — o
áudio não sai do PC; só o texto do pedido vai para a IA. (O motor “Navegador”, alternativo,
usa o serviço de fala do Chrome/Edge.)

## Tela “Mundo” (notícias, mercado e clima)

- **Resumo do dia** nos horários que você escolher (padrão 08:00) ou em “Gerar agora”.
- **Clima** da sua cidade (Open-Meteo) com previsão de 7 dias e avisos estimados.
- **Mercado:** sua lista (ex.: IBOV, USD, BTC, PETR4) com minigráficos; clique para o
  histórico com estatísticas. Indicadores oficiais do **Banco Central** (Selic, IPCA, CDI…).
- **Notícias** por tema e busca; **tendências** de busca no Brasil.
- **Alertas:** preço acima/abaixo, variação do dia, notícia com palavra-chave, clima — aparecem
  na tela, como notificação do Windows e (opcional) em voz. Também dá para pedir no chat:
  *“me avise se o dólar passar de 5,80”*.

Tudo mostra **fonte e horário**; estimativas são marcadas como estimativas e nada é
recomendação de investimento.

## Configuração (`.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `SEXTA_LLM_PROVIDER` | `auto` | De onde vem a IA: `auto` (assinatura via Claude Code; sem ele, chave da API), `assinatura`, `api` ou `offline` |
| `SEXTA_CLAUDE_PATH` | — | Caminho do `claude` se ele não estiver no PATH |
| `ANTHROPIC_API_KEY` | — | Opcional: chave da API paga (só usada sem o Claude Code ou com `SEXTA_LLM_PROVIDER=api`) |
| `SEXTA_PORT` | `8765` | Porta do servidor local |
| `SEXTA_DATA_DIR` | `%USERPROFILE%\.sexta-feira` | Banco, token, logs, lixeira, modelos e perfis de navegador |
| `SEXTA_WORKSPACE_DIR` | `%USERPROFILE%\SextaFeira` | Pasta de trabalho livre da assistente |
| `SEXTA_FS_EXTRA_ROOTS` | — | Pastas extras liberadas (separadas por `;`) |
| `SEXTA_DAILY_BUDGET_USD` | `5.0` | Orçamento diário inicial de API |
| `SEXTA_BROWSER` | Chrome → Edge | Navegador da janela da interface |
| `SEXTA_MODEL_FAST/BALANCED/DEEP` | Haiku 4.5 / Sonnet 5.5 / Opus 5.5 | Modelos de cada camada |

Preferências (autonomia, permissões, voz, cidade, ativos, temas, horários dos resumos,
orçamento, modelos, pastas) mudam pela interface.

## Custos

**Com a assinatura (padrão): nenhum custo extra.** A Sexta-Feira usa o Claude Code logado no
seu plano Pro — cada resposta consome um pouco do **limite de uso do plano** (janela de 5 horas
e limite semanal, os mesmos do claude.ai). O topo da tela mostra quanto já foi usado
(“Plano 25%”) e o Painel mostra quando renova. Se o limite acabar, a IA pausa até renovar;
voz, Mundo, memória e alertas continuam funcionando.

Dicas para render mais: prefira `/rapido` em perguntas simples; resumos automáticos e
subagentes também consomem o plano (dá para desligar os resumos em Configurações).

Voz local, memória semântica e as fontes de dados (notícias, clima, cotações, Banco Central)
são **gratuitas**. A API paga (créditos) só é usada se você configurar `SEXTA_LLM_PROVIDER=api`.

## Solução de problemas

| Sintoma | Solução |
|---|---|
| “Sem conexão com o servidor” / *Failed to fetch* | O servidor parou: rode `sexta status` para ver o motivo no fim do log e `sexta open` para ligar de novo. Para acompanhar ao vivo: `sexta stop` e depois `sexta serve` (deixe o terminal aberto) |
| “O Claude Code não está conectado à sua conta” | Abra o PowerShell, rode `claude`, entre com sua conta Pro e feche; depois `sexta stop` e `sexta open` |
| “Claude Code não encontrado” | Instale: `irm https://claude.ai/install.ps1 \| iex`; feche e abra o PowerShell; `sexta doctor` deve mostrar “IA em uso: Claude Pro (assinatura)” |
| “Você atingiu o limite de uso do seu plano” | Espere a renovação (o horário aparece na mensagem e no Painel) |
| “Sua conta está sem créditos” | Você está no modo API: tire `SEXTA_LLM_PROVIDER=api` do `.env` para voltar à assinatura |
| Não reage às palmas | Configurações → Voz: veja o medidor ao bater palmas; aumente a sensibilidade ou troque o microfone |
| “Voz local indisponível” | `sexta voz instalar` (precisa de internet uma vez) e `sexta voz testar` |
| Fala com sotaque/inglês | Instale a voz **Português (Brasil)** no Windows e escolha-a em Configurações → Voz |
| Busca por significado “indisponível” | `pip install -e ".[memoria]"` e `sexta memoria instalar` |
| Sites não abrem | `pip install -e ".[web]"`; o Edge do Windows é usado automaticamente |
| Não liga com o Windows | `sexta autostart status`; confira Gerenciador de Tarefas → Aplicativos de inicialização |
| Quero ver o que aconteceu | Log em `%USERPROFILE%\.sexta-feira\logs\sexta.log` e a tela **Atividade** |
| “Token de acesso inválido” | `sexta token` e use o link exibido |

## Para desenvolvimento

```powershell
pip install -e ".[completo,dev]"
pytest            # testes Python (+ testes JS se o Node.js estiver instalado; navegador real se houver Chromium)
ruff check .      # análise estática
```

Estrutura, decisões e segurança: [Arquitetura](docs/ARQUITETURA.md) ·
[Segurança](docs/SEGURANCA.md) · [Roadmap](docs/ROADMAP.md) · [Aprendizado](docs/APRENDIZADO.md)

```
src/sexta/
├── __main__.py      # CLI: serve, open, stop, autostart, voz, memoria, token, doctor
├── winsys.py        # Windows: iniciar com o sistema, janela, instância única
├── core/            # MEGABRAIN: roteador, orquestrador, prompts, eventos, tarefas, custos
├── llm/             # provedores de IA (Claude, offline) + catálogo de modelos
├── memory/          # SQLite, memórias (BM25 + semântica), conversas
├── security/        # permissões, guardas, aprovações, auditoria
├── tools/           # ferramentas: memória, arquivos, sistema, informações, agentes, navegador
├── agents/          # agentes especializados + delegação em paralelo
├── intel/           # notícias, clima, mercado, indicadores, alertas, resumos, agendador
├── browser/         # navegador controlado pela IA (Playwright) + guardas de rede
├── voice/           # voz local: microfone, palmas, ativação, Whisper, fala do Windows
├── api/             # REST + WebSocket
└── web/             # interface HUD (chat, painel, mundo, memória, atividade, config.)
```
