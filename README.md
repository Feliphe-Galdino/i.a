# SEXTA-FEIRA — sua assistente pessoal de IA

> Inspirada na F.R.I.D.A.Y. do Homem de Ferro: um centro de inteligência digital que
> conversa, programa, pesquisa, organiza, automatiza o computador e **aprende com você** —
> sempre dentro das permissões que você definir.

**Status:** Fase 1 concluída — fundação funcional, segura e modular.
Veja o [roadmap](docs/ROADMAP.md) para as próximas fases (voz, notícias, mercado, multiagentes…).

---

## O que já funciona (Fase 1)

| Módulo | O que faz |
|---|---|
| **MEGABRAIN** (roteador) | Escolhe sozinho o modelo ideal para cada pedido — **Haiku 4.5** (rápido/barato), **Sonnet 5.5** (equilibrado) ou **Opus 5.5** (programação e análises complexas) — e o nível de esforço de raciocínio. Considera complexidade, agente, sua prioridade (qualidade/equilíbrio/economia), urgência, tamanho do contexto e orçamento. Explica cada decisão. |
| **Agentes** | Programação, Pesquisa e Notícias, Análise Financeira, Automação, Organização Pessoal, Segurança e Monitoramento — selecionados automaticamente. |
| **Memória persistente** | Aprende fatos, preferências, projetos e correções; busca rápida sem acentos (SQLite FTS5); só as memórias relevantes vão para cada conversa. Você vê, edita, fixa, exporta, importa e apaga tudo. |
| **Histórico** | Todas as conversas salvas e pesquisáveis; a própria IA consegue consultar conversas e atividades anteriores. |
| **Controle do computador** | Ler/criar/editar/mover/buscar arquivos, executar comandos, ver sistema e processos, encerrar processos, abrir programas, arquivos e links. |
| **Segurança** | 4 níveis de autonomia, permissões por capacidade, confirmações para ações sensíveis, bloqueio de comandos catastróficos, pastas liberadas (sandbox), lixeira, auditoria completa, proteção de credenciais, orçamento diário e **botão PARAR**. |
| **Internet** | Pesquisa na web integrada (quando habilitada), com fontes. |
| **Interface futurista** | HUD inspirado no Homem de Ferro: chat em tempo real com raciocínio visível, cartões de ferramentas, aprovações, painel de sistema e custos, memória, auditoria e configurações. Funciona no PC e no celular. |

## Requisitos

- **Python 3.11 ou mais novo** — https://www.python.org/downloads/ (no Windows, marque *“Add Python to PATH”*).
- **Chave da API da Anthropic** (opcional para testar; sem ela roda em *modo offline*) — https://console.anthropic.com/settings/keys
- Git (para clonar o projeto).

## Instalação passo a passo

### Windows (PowerShell)

```powershell
git clone https://github.com/feliphe-galdino/i.a.git
cd i.a
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # se bloquear: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -e ".[dev]"
copy .env.example .env               # depois abra o .env e preencha ANTHROPIC_API_KEY
sexta doctor                         # verifica se está tudo certo
sexta serve                          # inicia e abre a interface no navegador
```

### macOS / Linux

```bash
git clone https://github.com/feliphe-galdino/i.a.git
cd i.a
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # depois edite e preencha ANTHROPIC_API_KEY
sexta doctor
sexta serve
```

Ao iniciar, o terminal mostra um link como `http://127.0.0.1:8765/?token=...`.
**Esse token é a chave da sua assistente** — não compartilhe. Para vê-lo de novo: `sexta token`.

## Primeiros passos

1. Abra **Configurações** e preencha seu nome e instruções personalizadas.
2. Escolha o **nível de autonomia** (comece em *Assistido*).
3. Se quiser que ela trabalhe nos seus projetos, adicione a pasta em **Pastas liberadas**.
4. Converse! Experimente:
   - “Lembre que eu prefiro exemplos em Python e explicações curtas.”
   - “Liste os arquivos da minha pasta de trabalho e sugira uma organização.”
   - “Como está o desempenho do meu computador?”
   - “/profundo Projete a arquitetura de uma API de tarefas com FastAPI.”

**Dicas:** `/rapido`, `/equilibrado` e `/profundo` no início da mensagem escolhem o modelo
manualmente. O seletor *Auto/Rápido/Equilibrado/Profundo* do chat faz o mesmo.

## Configuração (`.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Chave da API (sem ela: modo offline) |
| `SEXTA_HOST` / `SEXTA_PORT` | `127.0.0.1` / `8765` | Endereço do servidor (mantenha local) |
| `SEXTA_DATA_DIR` | `~/.sexta-feira` | Banco de dados, token e lixeira |
| `SEXTA_WORKSPACE_DIR` | `~/SextaFeira` | Pasta de trabalho livre da assistente |
| `SEXTA_FS_EXTRA_ROOTS` | — | Pastas extras liberadas (separadas por `;`) |
| `SEXTA_DAILY_BUDGET_USD` | `5.0` | Orçamento diário inicial de API |
| `SEXTA_TIMEZONE` | sistema | Fuso horário (ex.: `America/Sao_Paulo`) |
| `SEXTA_MODEL_FAST/BALANCED/DEEP` | Haiku 4.5 / Sonnet 5.5 / Opus 5.5 | Modelos de cada camada |
| `SEXTA_REFUSAL_FALLBACK` | `true` | Reexecuta em outro modelo se um filtro de segurança recusar por engano |

A maioria das preferências (autonomia, permissões, orçamento, modelos, pastas) pode ser
alterada direto na interface, sem reiniciar.

## Custos

Preços por milhão de tokens (entrada/saída): Haiku 4.5 US$ 1/5 · Sonnet 5.5 US$ 2/10 ·
Opus 5.5 US$ 4/20 · busca na web US$ 0,01 por busca. O cache de prompt reduz bastante o
custo de conversas longas. O painel mostra o gasto do dia e o roteador respeita o seu orçamento.

## Testes e qualidade

```bash
pytest            # 105+ testes: roteador, segurança, memória, orquestrador, provedor e API
ruff check .      # análise estática
ruff format .     # formatação
```

## Estrutura do projeto

```
i.a/
├── src/sexta/
│   ├── __main__.py          # CLI: sexta serve | token | doctor
│   ├── app.py               # FastAPI: API + WebSocket + interface
│   ├── config.py            # configuração do .env
│   ├── container.py         # montagem das peças (injeção de dependências)
│   ├── core/                # MEGABRAIN: roteador, orquestrador, prompts, eventos, tarefas, custos
│   ├── llm/                 # provedores de IA (Claude, offline) + catálogo de modelos
│   ├── memory/              # SQLite, memórias de longo prazo, conversas
│   ├── security/            # permissões, guardas, aprovações, auditoria
│   ├── tools/               # ferramentas: memória, arquivos, sistema/terminal
│   ├── agents/              # agentes especializados
│   ├── api/                 # rotas REST e WebSocket
│   └── web/                 # interface (HTML/CSS/JS sem etapa de build)
├── tests/                   # testes automatizados
└── docs/                    # arquitetura, segurança, roadmap, aprendizado
```

## Documentação

- [Arquitetura e decisões técnicas](docs/ARQUITETURA.md)
- [Modelo de segurança](docs/SEGURANCA.md)
- [Roadmap das próximas fases](docs/ROADMAP.md)
- [Guia de aprendizado (para evoluir junto com o projeto)](docs/APRENDIZADO.md)

## Solução de problemas

| Sintoma | Solução |
|---|---|
| “Token de acesso inválido” | Use o link do terminal ou rode `sexta token`. |
| Respostas dizem “modo offline” | Preencha `ANTHROPIC_API_KEY` no `.env` e reinicie. |
| “Acesso negado: fora das pastas liberadas” | Adicione a pasta em Configurações → Pastas liberadas. |
| Porta ocupada | `sexta serve --port 8800` |
| PowerShell bloqueia o `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
