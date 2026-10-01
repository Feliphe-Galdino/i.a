// Renderizador de Markdown seguro e sem dependências.
// Todo texto é escapado ANTES da formatação; só geramos tags conhecidas.
// Links aceitam apenas http(s). Suporta: títulos, listas, citações, tabelas,
// blocos de código (inclusive incompletos durante o streaming), negrito, itálico,
// código inline, links e linhas horizontais.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

const SENTINEL = "\u0000";

function inline(text) {
  const codes = [];
  let out = text.replace(/`([^`\n]+)`/g, (_, code) => {
    codes.push(`<code>${code}</code>`);
    return `${SENTINEL}C${codes.length - 1}${SENTINEL}`;
  });
  out = out
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`)
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, (_, pre, url) => `${pre}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
    .replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  return out.replace(new RegExp(`${SENTINEL}C(\\d+)${SENTINEL}`, "g"), (_, i) => codes[Number(i)]);
}

function splitRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

export function renderMarkdown(source) {
  const blocks = [];
  // 1) Blocos de código cercados (o último pode estar aberto durante o streaming)
  let text = String(source || "").replace(/\r\n/g, "\n");
  text = text.replace(/```([\w+#.-]*)[^\n]*\n([\s\S]*?)(```|$)/g, (_, lang, code) => {
    blocks.push({ lang, code: code.replace(/\n$/, "") });
    return `\n${SENTINEL}B${blocks.length - 1}${SENTINEL}\n`;
  });

  // 2) Escapa todo o resto
  const lines = escapeHtml(text).split("\n");
  const html = [];
  let para = [];
  let list = null; // { type: "ul" | "ol", items: [] }

  const flushPara = () => {
    if (para.length) html.push(`<p>${inline(para.join("<br>"))}</p>`);
    para = [];
  };
  const flushList = () => {
    if (list) html.push(`<${list.type}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.type}>`);
    list = null;
  };
  const flush = () => { flushPara(); flushList(); };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    const block = trimmed.match(new RegExp(`^${SENTINEL}B(\\d+)${SENTINEL}$`));
    if (block) { flush(); html.push(`${SENTINEL}B${block[1]}${SENTINEL}`); continue; }
    if (!trimmed) { flush(); continue; }

    const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { flush(); const n = heading[1].length; html.push(`<h${n}>${inline(heading[2])}</h${n}>`); continue; }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) { flush(); html.push("<hr>"); continue; }

    if (trimmed.startsWith("&gt;")) {
      flush();
      const quote = [];
      while (i < lines.length && lines[i].trim().startsWith("&gt;")) {
        quote.push(lines[i].trim().replace(/^&gt;\s?/, ""));
        i++;
      }
      i--;
      html.push(`<blockquote>${inline(quote.join("<br>"))}</blockquote>`);
      continue;
    }

    // Tabela: linha com | seguida de separador |---|
    if (trimmed.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      flush();
      const head = splitRow(trimmed);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { rows.push(splitRow(lines[i])); i++; }
      i--;
      html.push(
        `<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>` +
        rows.map((r) => `<tr>${head.map((_, j) => `<td>${inline(r[j] ?? "")}</td>`).join("")}</tr>`).join("") +
        "</tbody></table>",
      );
      continue;
    }

    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const type = ul ? "ul" : "ol";
      if (!list || list.type !== type) { flushList(); list = { type, items: [] }; }
      list.items.push((ul || ol)[1]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(line)) { list.items[list.items.length - 1] += `<br>${trimmed}`; continue; }

    flushList();
    para.push(trimmed);
  }
  flush();

  // 3) Reinsere os blocos de código (conteúdo escapado)
  return html.join("\n").replace(new RegExp(`${SENTINEL}B(\\d+)${SENTINEL}`, "g"), (_, idx) => {
    const { lang, code } = blocks[Number(idx)];
    const label = lang ? `<span class="lang">${escapeHtml(lang)}</span>` : "";
    return `<pre>${label}<button class="btn ghost small copy" type="button">copiar</button><code>${escapeHtml(code)}</code></pre>`;
  });
}
