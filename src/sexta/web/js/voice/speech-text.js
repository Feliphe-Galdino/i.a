// Texto ↔ fala: frase de ativação, comandos de controle e texto "falável".
// Funções puras, testadas no Node (tests/js/speech-text.test.mjs).

const stripAccents = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Normaliza uma palavra do reconhecedor: minúsculas, sem acentos e sem pontuação. */
export function normWord(word) {
  return stripAccents(String(word).toLowerCase()).replace(/ª/g, "a").replace(/[^a-z0-9]/g, "");
}

export function normalizeSpeech(text) {
  return stripAccents(String(text || "").toLowerCase())
    .replace(/ª/g, "a")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

const NAME_SINGLE = new Set(["sextafeira", "6afeira", "sestafeira", "cestafeira", "sextafeiras", "sexyfeira"]);
const NAME_FIRST = new Set(["sexta", "sesta", "cesta", "6a", "6", "sexy"]);
const GREET_ONE = new Set(["ola", "oi", "ei", "hey", "alo", "opa", "eai", "fala", "hello"]);
const GREET_TWO = new Set(["e ai", "bom dia", "boa tarde", "boa noite", "ola ola"]);

/**
 * Procura "Olá, Sexta-Feira" (e variações: oi/ei/bom dia… + Sexta-Feira).
 * Retorna { command } com o que foi dito depois do nome (pode ser vazio), ou null.
 * Com nameOnly=true, aceita também o nome no início da frase ("Sexta-Feira, abra…").
 */
export function matchWake(text, { nameOnly = false } = {}) {
  const tokens = String(text || "").trim().split(/\s+/).filter(Boolean);
  const norm = tokens.map(normWord);
  for (let i = 0; i < norm.length; i++) {
    let nameEnd = -1;
    if (NAME_SINGLE.has(norm[i])) nameEnd = i;
    else if (NAME_FIRST.has(norm[i]) && norm[i + 1] === "feira") nameEnd = i + 1;
    if (nameEnd < 0) continue;
    const greeted =
      (i > 0 && GREET_ONE.has(norm[i - 1])) || (i > 1 && GREET_TWO.has(`${norm[i - 2]} ${norm[i - 1]}`));
    if (greeted || (nameOnly && i === 0)) {
      const command = tokens.slice(nameEnd + 1).join(" ").replace(/^[\s,.!?;:—-]+/, "").trim();
      return { command };
    }
  }
  return null;
}

const CONTROL = [
  ["silence", /^(silencio|cala a boca|chega|para de falar|pare de falar|quieta|fica quieta|shh+)\b/],
  ["stop", /^(parar|pare|para tudo|interromper|interrompa|abortar|aborta|cancelar tarefa|cancela tudo)\b/],
  ["yes", /^(sim|pode|pode sim|pode fazer|confirmo|confirmar|confirmado|aprovo|aprovado|autorizo|positivo|claro|manda ver|ok pode)\b/],
  ["no", /^(nao|negativo|nega|negar|negado|recuso|nao pode|cancela|cancelar|de jeito nenhum)\b/],
];

/** Identifica comandos curtos de controle. Retorna "silence" | "stop" | "yes" | "no" | null. */
export function matchControl(text) {
  const norm = normalizeSpeech(text);
  if (!norm || norm.split(" ").length > 6) return null;
  for (const [kind, pattern] of CONTROL) if (pattern.test(norm)) return kind;
  return null;
}

/** Converte Markdown em texto bom para ser falado, limitado a ~maxChars. */
export function toSpeakable(markdown, { maxChars = 600 } = {}) {
  let text = String(markdown || "");
  const hadCode = /```/.test(text);
  text = text
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(/^\s*\|.*\|\s*$/gm, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "link")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*(\d+)[.)]\s+/gm, "$1. ")
    .replace(/(\*\*|__|\*|_|~~)/g, "")
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\.(\s*\.)+/g, ".")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (text.length > maxChars) {
    const cut = text.slice(0, maxChars);
    const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
    text = `${end > maxChars * 0.4 ? cut.slice(0, end + 1) : cut.trimEnd() + "…"} O restante está na tela.`;
  }
  if (hadCode) text = `${text} Coloquei o código na tela.`.trim();
  return text.replace(/^\.\s*/, "");
}

/** Divide em frases curtas (o Chrome corta falas muito longas). */
export function chunkSentences(text, maxLen = 180) {
  const sentences = String(text || "").match(/[^.!?…]+[.!?…]*\s*/g) || [];
  const chunks = [];
  let current = "";
  for (const sentence of sentences) {
    if ((current + sentence).length > maxLen && current) {
      chunks.push(current.trim());
      current = "";
    }
    if (sentence.length > maxLen) {
      for (let i = 0; i < sentence.length; i += maxLen) chunks.push(sentence.slice(i, i + maxLen).trim());
    } else {
      current += sentence;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.filter(Boolean);
}

/** Encurta caminhos de arquivo para a fala ("C:\Users\eu\docs\a.md" → "a.md"). */
export function shortenPaths(text) {
  return String(text || "")
    .replace(/[A-Za-z]:\\[^\s"']+/g, (p) => p.split("\\").filter(Boolean).pop())
    .replace(/(^|\s)(\/[^\s"']+)/g, (_, pre, p) => pre + p.split("/").filter(Boolean).pop());
}
