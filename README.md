# SEXTA-FEIRA — sua assistente pessoal de IA

> Inspirada na F.R.I.D.A.Y. do Homem de Ferro: um centro de inteligência digital que
> conversa, programa, pesquisa, organiza, automatiza o computador e **aprende com você**.
> Liga junto com o Windows e atende a **duas palmas** ou a um **“Olá, Sexta-Feira”**.

**Plataforma:** Windows 11 · **Status:** Fase 2 concluída (voz e início automático).
Veja o [roadmap](docs/ROADMAP.md).

---

## O que ela já faz

| Módulo | O que faz |
|---|---|
| **Voz** | Ativação por **“Olá, Sexta-Feira”** ou **duas palmas**; entende o pedido falado (pt-BR) e **responde em voz alta**. Modos *Texto*, *Voz* ou *Ambos*. Confirma ações por voz (“sim”/“não”). “Silêncio” e “parar” a qualquer momento. |
| **Inicia com o Windows** | Ao entrar no Windows, o servidor sobe oculto e abre a janela da Sexta-Feira já escutando — sem precisar de administrador. |
| **MEGABRAIN** | Escolhe sozinho o modelo ideal: **Haiku 4.5** (rápido/barato), **Sonnet 5.5** (equilibrado) ou **Opus 5.5** (programação e análises complexas), e o nível de raciocínio — explicando cada decisão. |
| **Agentes** | Programação, Pesquisa e Notícias, Finanças, Automação, Organização, Segurança — escolhidos automaticamente. |
| **Memória** | Aprende fatos, preferências, projetos e correções; você vê, edita, fixa, exporta e apaga tudo. |
| **Controle do PC** | Arquivos, terminal, processos, programas e links — sempre dentro das permissões. |
| **Segurança** | Níveis de autonomia, confirmações, bloqueio de comandos perigosos, pastas liberadas, lixeira, auditoria, orçamento diário e botão **PARAR**. |
| **Interface** | HUD futurista: chat em tempo real, painel, memória, auditoria e configurações. |

## Instalação (Windows 11)

### 1. Pré-requisitos

- **Python 3.11+** — https://www.python.org/downloads/ (marque **“Add Python to PATH”** na instalação).
- **Git** — https://git-scm.com/download/win
- **Google Chrome** (recomendado para o reconhecimento de voz; o Edge também funciona).
- **Chave da API da Anthropic com créditos** — https://console.anthropic.com/settings/keys
  (sem créditos a API responde *“credit balance is too low”*; adicione em **Plans & Billing**).

### 2. Instalar

Abra o **PowerShell** e rode:

```powershell
cd $HOME
git clone https://github.com/feliphe-galdino/i.a.git
cd i.a
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # se bloquear: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e .
copy .env.example .env
notepad .env                         # cole sua chave em ANTHROPIC_API_KEY= e salve
sexta doctor                         # verifica se está tudo certo
```

### 3. Primeiro uso

```powershell
sexta open
```

Abre a **janela da Sexta-Feira** (Chrome em modo aplicativo). Na primeira vez:

1. **Permita o microfone** quando o navegador pedir (ele lembra depois).
2. Bata **duas palmas** ou diga **“Olá, Sexta-Feira”** → um bipe indica que ela está ouvindo.
3. Faça o pedido: *“que horas são?”*, *“como está o desempenho do meu computador?”*…

### 4. Iniciar junto com o Windows

```powershell
sexta autostart on
```

Pronto: ao ligar o PC e entrar no Windows, a Sexta-Feira sobe sozinha e abre a janela
já escutando. Pode deixar a janela **minimizada** — ela continua ouvindo.
(Também dá para ligar/desligar em **Configurações → Voz e ativação**.)

## Comandos

| Comando | O que faz |
|---|---|
| `sexta open` | Abre a janela da assistente (sobe o servidor em segundo plano se preciso) |
| `sexta serve` | Roda o servidor neste terminal (útil para ver mensagens) |
| `sexta stop` | Encerra o servidor que está em segundo plano |
| `sexta autostart on` / `off` / `status` | Iniciar com o Windows |
| `sexta token` | Mostra o token de acesso (a “senha” da interface) |
| `sexta doctor` | Diagnóstico da instalação |

## Usando a voz

| Você diz / faz | Ela faz |
|---|---|
| 👏👏 ou “Olá, Sexta-Feira” | Bipe e começa a ouvir (8 s) |
| “Olá, Sexta-Feira, abra a calculadora” | Ativa e já executa o pedido |
| “Silêncio” (ou 👏👏 enquanto fala) | Para de falar |
| “Parar” | Interrompe as tarefas em andamento |
| “Sim” / “Não” | Responde a pedidos de confirmação (só ações **não críticas**; críticas exigem clique) |

Também funcionam “Oi/Ei/Bom dia, Sexta-Feira”. Ajuste a **sensibilidade das palmas** em
Configurações → Voz e ativação (há um medidor ao vivo para calibrar) e escolha a voz.

**Modos de interação:** *Texto* (sem microfone) · *Ambos* (fala só as respostas a pedidos
falados — padrão da janela de voz) · *Voz* (fala todas as respostas).

**Privacidade:** as palmas são detectadas **no seu computador**. O reconhecimento de fala do
navegador envia o áudio ao serviço do Google (Chrome) ou da Microsoft (Edge) enquanto escuta.
Se preferir, desligue “Olá, Sexta-Feira” e ative só por palmas/botão — aí o áudio só é enviado
depois da ativação.

## Configuração (`.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Chave da API (sem ela: modo offline) |
| `SEXTA_PORT` | `8765` | Porta do servidor local |
| `SEXTA_DATA_DIR` | `%USERPROFILE%\.sexta-feira` | Banco, token, logs, lixeira e perfil da janela de voz |
| `SEXTA_WORKSPACE_DIR` | `%USERPROFILE%\SextaFeira` | Pasta de trabalho livre da assistente |
| `SEXTA_FS_EXTRA_ROOTS` | — | Pastas extras liberadas (separadas por `;`) |
| `SEXTA_DAILY_BUDGET_USD` | `5.0` | Orçamento diário inicial de API |
| `SEXTA_BROWSER` | Chrome → Edge | Caminho do navegador da janela de voz |
| `SEXTA_MODEL_FAST/BALANCED/DEEP` | Haiku 4.5 / Sonnet 5.5 / Opus 5.5 | Modelos de cada camada |

Preferências como autonomia, permissões, orçamento, modelos e pastas mudam pela interface.

## Custos

Preço por milhão de tokens (entrada/saída): Haiku 4.5 US$ 1/5 · Sonnet 5.5 US$ 2/10 ·
Opus 5.5 US$ 4/20 · busca na web US$ 0,01. A voz do navegador é **gratuita**. O painel mostra
o gasto do dia e o roteador respeita o orçamento.

## Solução de problemas

| Sintoma | Solução |
|---|---|
| “Sua conta está sem créditos” | Adicione créditos em console.anthropic.com → Plans & Billing |
| Não reage às palmas | Configurações → Voz: veja o medidor ao bater palmas; aumente a sensibilidade |
| “O microfone foi bloqueado” | Clique no cadeado da barra da janela → Microfone → Permitir |
| Não liga com o Windows | `sexta autostart status`; confira também Gerenciador de Tarefas → Aplicativos de inicialização |
| Quero ver o que aconteceu | Log em `%USERPROFILE%\.sexta-feira\logs\sexta.log` e a tela **Atividade** |
| “Token de acesso inválido” | `sexta token` e use o link exibido |
| PowerShell bloqueia o `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

## Para desenvolvimento

```powershell
pip install -e ".[dev]"
pytest            # testes Python (+ testes JS se o Node.js estiver instalado)
ruff check .      # análise estática
```

Estrutura, decisões e segurança: [Arquitetura](docs/ARQUITETURA.md) ·
[Segurança](docs/SEGURANCA.md) · [Roadmap](docs/ROADMAP.md) · [Aprendizado](docs/APRENDIZADO.md)

```
src/sexta/
├── __main__.py      # CLI: serve, open, stop, autostart, token, doctor
├── winsys.py        # Windows: iniciar com o sistema, janela de voz, instância única
├── core/            # MEGABRAIN: roteador, orquestrador, prompts, eventos, tarefas, custos
├── llm/             # provedores de IA (Claude, offline) + catálogo de modelos
├── memory/          # SQLite, memórias, conversas
├── security/        # permissões, guardas, aprovações, auditoria
├── tools/           # ferramentas: memória, arquivos, sistema/terminal
├── agents/          # agentes especializados
├── api/             # REST + WebSocket
└── web/             # interface HUD + voz (js/voice: palmas, fala, ativação)
```
