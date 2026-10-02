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
`web.search`, `memory.write`…), sobrepondo o nível de autonomia. “Negar” bloqueia por
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

- **Palmas:** detectadas localmente (AudioWorklet); nenhum áudio sai do computador.
- **Fala:** o reconhecimento do navegador envia o áudio ao serviço de fala do Google (Chrome)
  ou da Microsoft (Edge) **enquanto escuta**. Com “Olá, Sexta-Feira” desligado, ele só escuta
  depois das palmas ou do botão.
- **Confirmações por voz** valem apenas para ações não críticas. Ações **críticas** sempre
  exigem clique na tela — uma TV ou outra pessoa dizendo “sim” não basta.
- A janela de voz usa um **perfil próprio do navegador** dentro da pasta de dados protegida;
  a permissão de microfone vale só para a Sexta-Feira (`http://127.0.0.1:8765`).

## Início automático

- Usa a chave `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` do seu usuário
  (sem privilégios de administrador). O comando registrado é montado pelo próprio sistema.
- Desligue com `sexta autostart off`, pela interface ou pelo Gerenciador de Tarefas.
- `sexta stop` encerra o servidor oculto; o servidor nunca abre portas fora de `127.0.0.1`.

## Limitações conhecidas (honestidade)

- Um comando aprovado roda com as permissões do seu usuário no sistema: leia o resumo
  antes de aprovar ações de execução.
- A classificação de comandos é por padrões; comandos ofuscados podem não ser detectados
  como críticos — por isso o nível padrão (*Assistido*) pede confirmação para **qualquer**
  execução.
- Ao cancelar uma tarefa durante um comando de terminal, o comando em andamento termina
  sozinho (até o tempo limite); a tarefa não continua depois dele.
