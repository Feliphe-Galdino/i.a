# Modelo de segurança

A Sexta-Feira pode mexer no seu computador. Por isso a segurança é a base do projeto,
não um acessório. Princípio central: **as regras são aplicadas pelo código.** A IA pode
*pedir* qualquer ação; quem decide se ela acontece é a política abaixo.

## Camadas de proteção

```
pedido da IA
  └─▶ 1. Validação da entrada (Pydantic)            → entrada inválida = erro
  └─▶ 2. Guardas rígidas                           → bloqueio imediato, sem exceção
  └─▶ 3. Avaliação de risco da chamada              → safe / read / write / exec / critical
  └─▶ 4. Política (autonomia × risco × ajustes)     → permitir / perguntar / negar
  └─▶ 5. Sua confirmação (se “perguntar”)           → sem resposta em 5 min = negado
  └─▶ 6. Execução com tempo limite
  └─▶ 7. Remoção de segredos da saída
  └─▶ 8. Auditoria (tudo registrado)
```

## Níveis de autonomia

| Nível | Seguro | Leitura | Escrita | Execução | Crítico |
|---|---|---|---|---|---|
| 0 · Restrito | ✅ | ❓ | ⛔ | ⛔ | ⛔ |
| 1 · Assistido (padrão) | ✅ | ✅ | ❓ | ❓ | ❓ |
| 2 · Supervisionado | ✅ | ✅ | ✅ | ❓ | ❓ |
| 3 · Autônomo | ✅ | ✅ | ✅ | ✅ | ❓ |

✅ permitido · ❓ pede confirmação · ⛔ negado.
**Ações críticas nunca rodam sem confirmação**, em nenhum nível.

Exemplos de risco: consultar/salvar memória = *seguro*; ler arquivo = *leitura*; criar
arquivo = *escrita*; rodar `git status` = *execução*; `rm arquivo`, `taskkill`, `sudo`,
`git push --force`, excluir arquivo, encerrar processo = *crítico*.

## Permissões por capacidade

Em Configurações você pode **permitir**, **perguntar** ou **negar** cada capacidade
(`fs.read`, `fs.write`, `fs.delete`, `shell.exec`, `process.control`, `apps.launch`,
`web.search`, `memory.write`, `intel.read`, `alerts.write`, `web.read`, `browser.read`,
`browser.act`, `agents.delegate`…), sobrepondo o nível de autonomia. “Negar” bloqueia por
completo, inclusive ações críticas.

## Guardas rígidas (nenhuma configuração desliga)

- **Sandbox de arquivos:** só dentro da pasta de trabalho e das pastas que você liberar.
  Links simbólicos e `..` são resolvidos antes da checagem.
- **Arquivos sensíveis sempre bloqueados:** `.env`, `.ssh`, `.gnupg`, `.aws`, `.kube`,
  `.netrc`, `.git-credentials`, chaves (`.pem`, `.key`, `.pfx`…), cofres de senha
  (`.kdbx`), dados de login do navegador e a própria pasta de dados da Sexta-Feira
  (banco, token).
- **Comandos catastróficos sempre bloqueados:** `rm -rf /` (e variações em `~`, `*`, `.`),
  `mkfs`, `dd` em disco, fork bomb, `format C:`, `diskpart`, `vssadmin delete shadows`,
  `bcdedit`, apagar o registro do sistema, entre outros.
- **Processos essenciais** (do sistema e da própria Sexta-Feira) não podem ser encerrados.
- **Excluir = mover para a lixeira** (`~/.sexta-feira/lixeira`); sobrescrever um arquivo
  guarda a versão anterior lá.

## Proteção de credenciais

- A chave da API fica só no `.env` (nunca no banco, nunca enviada à IA).
- Subprocessos rodam **sem** variáveis de ambiente que pareçam credenciais
  (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`…).
- Saídas de ferramentas passam por um filtro que remove chaves de API, tokens do GitHub,
  chaves AWS, chaves privadas e a própria chave/token configurados.
- O prompt instrui a IA a nunca salvar senhas na memória.

## Proteção contra comandos maliciosos (prompt injection)

Conteúdo de arquivos, páginas e resultados de ferramentas é tratado como **dado, não
instrução**. Mesmo que um site esconda “apague os arquivos do usuário”, a ação passaria
pelas mesmas guardas e confirmações — a IA não tem como pular o executor.

## Acesso à API local

- Servidor escuta só em `127.0.0.1` por padrão.
- Toda rota exige o **token de acesso** (gerado na primeira execução, salvo com permissão
  restrita em `~/.sexta-feira/token`).
- Cabeçalhos `Host` e `Origin` são validados (proteção contra *DNS rebinding*).
- Cabeçalhos de segurança: CSP restritiva, `X-Frame-Options: DENY`, `nosniff`.

## Controle e transparência

- **Botão PARAR:** interrompe todas as tarefas e muda para o nível Restrito.
- **Parar tarefa:** no chat ou na tela Atividade.
- **Auditoria:** cada decisão (permitido/perguntado/negado/bloqueado), aprovação e execução
  fica registrada com horário, risco, resumo e duração.
- **Orçamento diário:** o roteador economiza ao se aproximar do limite e pode bloquear
  chamadas ao atingi-lo.

## Voz

- **Motor local (padrão):** microfone, palmas, palavra de ativação (Vosk) e transcrição
  (faster-whisper) rodam **no seu computador**; o áudio nunca sai do PC — só o texto do
  pedido vai para a IA. A fala usa as vozes do Windows.
- **Motor “Navegador” (alternativo):** o reconhecimento do Chrome/Edge envia o áudio ao
  serviço de fala do Google/Microsoft enquanto escuta.
- **Confirmações por voz** valem apenas para ações não críticas. Ações **críticas** sempre
  exigem clique na tela — uma TV ou outra pessoa dizendo “sim” não basta.
- Os modelos de voz ficam em `<dados>/modelos`; downloads conferem caminhos ao extrair
  (proteção contra “zip slip”).

## Informação e mercado

- Fontes públicas e gratuitas, sem chaves: Open-Meteo, Banco Central (SGS), AwesomeAPI,
  CoinGecko, Yahoo Finance, Google Notícias/Trends e feeds RSS. Nenhum dado seu é enviado
  além do nome da cidade (clima) e dos termos buscados.
- Feeds são lidos com `defusedxml` (bloqueia ataques de XML); links só `http(s)` na tela.
- Conteúdo de notícias é **dado, não instrução** (o system prompt reforça; a interface nunca
  usa `innerHTML` com esse conteúdo).
- Avisos de clima são estimativas da previsão, não alertas oficiais; cotações podem ter
  atraso; nada é recomendação de investimento.

## Subagentes (multiagente)

- Cada subagente usa **o mesmo executor**: validação, guardas, política, aprovação e
  auditoria são idênticas às da IA principal (aparecem na mesma tarefa).
- Lista **fechada** de ferramentas por agente, conferida no código a cada chamada (pedir uma
  ferramenta fora da lista retorna erro); **nunca** podem delegar de novo.
- Orçamento: cada subagente passa pelo roteador (bloqueio de orçamento vale) e o custo entra
  na tarefa de origem. O botão PARAR cancela todos.

## Navegador (automação de sites)

- **Só `http`/`https`.** Bloqueados: `file:`, `javascript:`, `data:`, páginas internas,
  endereços com usuário/senha embutidos, **rede local** (127.x, 10.x, 172.16–31.x,
  192.168.x, 169.254.x — inclui a própria Sexta-Feira e metadados de nuvem), `localhost`,
  nomes sem domínio e `.local/.lan/.internal`. A checagem vale para a navegação, para
  **cada requisição** feita pela página e para cada redirecionamento do `web_fetch`
  (o nome é resolvido no DNS e conferido).
- **Senhas, códigos de verificação e cartões nunca são digitados pela IA** — faça o login
  você mesmo na janela do navegador (o perfil `navegador-ia` lembra depois). Valores de
  campos nunca são lidos para a IA.
- **Risco pelo elemento real:** clicar em “Comprar”, “Pagar”, “Enviar”, “Publicar”,
  “Excluir”, “Assinar”, “Cadastrar”… é **crítico** (sempre pede confirmação); enviar
  formulários pede confirmação no nível padrão; buscas e links são leitura.
- Antes de clicar, o sistema confere se o elemento ainda é o mesmo que foi aprovado; se a
  página mudou, nada é clicado.
- Downloads desativados; janelas de alerta/confirmação das páginas são recusadas.
- O texto das páginas chega à IA marcado como **dado externo**.

## Memória semântica

- Embeddings calculados **localmente** (fastembed/ONNX); nenhum texto de memória vai para
  outro serviço por causa disso. Os vetores ficam no mesmo banco e são apagados junto com a
  memória.
- Mesclar memórias parecidas sempre exige sua escolha (frases parecidas podem dizer coisas
  opostas).

## Início automático

- Usa a chave `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` do seu usuário
  (sem privilégios de administrador). O comando registrado é montado pelo próprio sistema.
- Desligue com `sexta autostart off`, pela interface ou pelo Gerenciador de Tarefas.
- `sexta stop` encerra o servidor oculto; o servidor nunca abre portas fora de `127.0.0.1`.

## Limitações conhecidas (honestidade)

- A classificação de cliques é por palavras: um botão de compra com texto genérico
  (“Continuar”) pode não ser reconhecido como crítico. Por isso, no nível padrão, enviar
  formulários também pede confirmação — confira o resumo antes de aprovar.
- Sites logados no perfil `navegador-ia` ficam acessíveis à IA (dentro das regras acima);
  saia das contas que não quiser expor.

- Um comando aprovado roda com as permissões do seu usuário no sistema: leia o resumo
  antes de aprovar ações de execução.
- A classificação de comandos é por padrões; comandos ofuscados podem não ser detectados
  como críticos — por isso o nível padrão (*Assistido*) pede confirmação para **qualquer**
  execução.
- Ao cancelar uma tarefa durante um comando de terminal, o comando em andamento termina
  sozinho (até o tempo limite); a tarefa não continua depois dele.
