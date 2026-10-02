// Testes da frase de ativação, comandos de controle e texto falável (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { chunkSentences, matchControl, matchWake, toSpeakable } from "../../src/sexta/web/js/voice/speech-text.js";

test("reconhece 'Olá, Sexta-Feira' com variações do reconhecedor", () => {
  for (const phrase of ["Olá, Sexta-Feira", "olá sexta feira", "Oi Sexta-feira!", "ei sexta feira", "Bom dia, Sexta-Feira", "olá 6ª feira", "Olá sextafeira"]) {
    assert.deepEqual(matchWake(phrase), { command: "" }, phrase);
  }
});

test("separa o comando dito junto com a ativação", () => {
  assert.deepEqual(matchWake("Olá, Sexta-Feira, que horas são?"), { command: "que horas são?" });
  assert.deepEqual(matchWake("hmm oi sexta-feira abra o bloco de notas"), { command: "abra o bloco de notas" });
});

test("não ativa com o nome no meio de uma conversa", () => {
  assert.equal(matchWake("na sexta-feira eu vou ao cinema"), null);
  assert.equal(matchWake("hoje é sexta feira"), null);
  assert.equal(matchWake("olá tudo bem"), null);
  assert.equal(matchWake(""), null);
});

test("modo 'só o nome' aceita o nome no início", () => {
  assert.deepEqual(matchWake("Sexta-Feira, abra o Chrome", { nameOnly: true }), { command: "abra o Chrome" });
  assert.equal(matchWake("na sexta-feira", { nameOnly: true }), null);
});

test("comandos de controle", () => {
  assert.equal(matchControl("Silêncio!"), "silence");
  assert.equal(matchControl("pare de falar"), "silence");
  assert.equal(matchControl("parar"), "stop");
  assert.equal(matchControl("Sim, pode"), "yes");
  assert.equal(matchControl("confirmo"), "yes");
  assert.equal(matchControl("não"), "no");
  assert.equal(matchControl("para que serve isso"), null);
  assert.equal(matchControl("parece bom"), null);
  assert.equal(matchControl("sim mas antes me explique detalhadamente o que vai acontecer com tudo"), null);
});

test("transforma Markdown em texto falável", () => {
  const md = "## Resultado\n\n**Pronto!** Veja o [site](https://exemplo.com).\n\n- item um\n- item dois\n\n```python\nprint('oi')\n```";
  const spoken = toSpeakable(md);
  assert.ok(!/[#*`\[\]]/.test(spoken), spoken);
  assert.ok(spoken.includes("Pronto!"));
  assert.ok(spoken.includes("site"));
  assert.ok(spoken.endsWith("Coloquei o código na tela."), spoken);
  assert.ok(!spoken.includes("print"));
});

test("limita respostas longas", () => {
  const long = "Frase de teste com várias palavras. ".repeat(60);
  const spoken = toSpeakable(long, { maxChars: 200 });
  assert.ok(spoken.length < 260);
  assert.ok(spoken.endsWith("O restante está na tela."));
});

test("divide em frases curtas", () => {
  const chunks = chunkSentences("Primeira frase. Segunda frase! Terceira? " + "x".repeat(400), 180);
  assert.ok(chunks.every((c) => c.length <= 180));
  assert.equal(chunks[0], "Primeira frase. Segunda frase! Terceira?");
});

test("encurta caminhos para a fala", async () => {
  const { shortenPaths } = await import("../../src/sexta/web/js/voice/speech-text.js");
  assert.equal(shortenPaths("Substituir C:\\Users\\Feliphe\\SextaFeira\\ideias.md (50 caracteres)"), "Substituir ideias.md (50 caracteres)");
  assert.equal(shortenPaths("Listar a pasta /home/eu/projetos/app"), "Listar a pasta app");
});
