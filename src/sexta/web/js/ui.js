// Utilitários de interface: criação de elementos, toasts, formatação.

/**
 * Cria elementos sem innerHTML (seguro contra XSS).
 * h("div", { class: "x", onclick: fn }, "texto", outroElemento)
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

/** Acrescenta filhos aceitando listas e ignorando null/false (o append nativo não faz isso). */
export function add(el, ...children) { append(el, children); return el; }

/** Limpa e preenche um elemento. */
export function fill(el, ...children) { return add(clear(el), ...children); }

export function toast(message, kind = "info", ms = 4200) {
  const root = document.getElementById("toasts");
  // A mesma mensagem já está na tela? Não empilha cópias (ex.: várias requisições falhando juntas).
  for (const existing of root.children) if (existing.textContent === String(message)) return;
  const el = h("div", { class: `toast ${kind}` }, message);
  root.append(el);
  setTimeout(() => el.remove(), ms);
}

export const fmt = {
  usd(value) {
    const n = Number(value || 0);
    return n < 0.01 && n > 0 ? `US$ ${n.toFixed(4)}` : `US$ ${n.toFixed(2)}`;
  },
  num(value) { return new Intl.NumberFormat("pt-BR").format(Number(value || 0)); },
  time(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  },
  ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "agora";
    if (s < 3600) return `${Math.floor(s / 60)} min`;
    if (s < 86400) return `${Math.floor(s / 3600)} h`;
    return `${Math.floor(s / 86400)} d`;
  },
  json(value) {
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  },
};

export const RISK_LABEL = { safe: "Seguro", read: "Leitura", write: "Escrita", exec: "Execução", critical: "Crítico" };
export const STATUS_LABEL = {
  pending: "preparando", evaluating: "avaliando", awaiting_approval: "aguardando você", running: "executando",
  done: "concluído", error: "erro", blocked: "bloqueado", denied: "negado", rejected: "recusado",
};
export const TASK_STATUS = {
  running: "em andamento", done: "concluída", error: "erro", cancelled: "cancelada", refused: "recusada",
  blocked: "bloqueada", incomplete: "incompleta", interrupted: "interrompida",
};

export function riskTag(risk) {
  return h("span", { class: `tag risk-${risk}` }, RISK_LABEL[risk] || risk);
}

/** Retorna um "debounce" simples. */
export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function download(filename, text, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
