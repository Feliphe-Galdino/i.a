// Gráficos em SVG puro (sem bibliotecas).
//
// Regras seguidas (ver docs/APRENDIZADO.md → visualização de dados):
// * linha de 2px com área a 10% (uma "lavagem", nunca um bloco saturado);
// * grade e eixos em linha fina sólida, discretos; o dado é a única coisa "alta";
// * rótulo direto só no último valor; o resto fica no eixo, na dica e na tabela;
// * cursor (linha vertical) que acha o ponto mais próximo — com mouse, toque ou setas do teclado;
// * textos sempre com textContent (nomes e valores vêm da internet).

import { h } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

function svgText(attrs, text) {
  const el = svg("text", attrs);
  el.textContent = text;
  return el;
}

/** Marcas "redondas" do eixo Y (1, 2 ou 5 × 10^n) cobrindo [min, max]. */
export function niceTicks(min, max, count = 4) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { ticks: [], lo: 0, hi: 1, step: 1 };
  if (min === max) {
    const pad = Math.abs(min) * 0.01 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toPrecision(12)));
  return { ticks, lo, hi, step };
}

/** Casas decimais suficientes para distinguir as marcas do eixo. */
export function stepDecimals(step) {
  return Math.min(4, Math.max(0, -Math.floor(Math.log10(step))));
}

const shortDate = (iso) => {
  const [, m, d] = String(iso).slice(0, 10).split("-");
  return d && m ? `${d}/${m}` : String(iso);
};
const longDate = (iso) => {
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  return d && m && y ? `${d}/${m}/${y}` : String(iso);
};

/**
 * Gráfico de linha de uma série.
 * opts: { dates, values, format(v), label, compact, height }
 * compact = minilinha (sem eixos), usada nos cartões de cotação.
 */
export function lineChart({ dates = [], values = [], format = (v) => String(v), compactFormat = null, label = "", compact = false, height } = {}) {
  const points = values.map((v, i) => [dates[i], Number(v)]).filter(([, v]) => Number.isFinite(v));
  const n = points.length;
  const first = n ? points[0][1] : null;
  const last = n ? points[n - 1][1] : null;
  const changePct = n > 1 && first ? ((last / first - 1) * 100).toFixed(2).replace(".", ",") : null;
  const summary = n
    ? `${label}: de ${format(first)} (${longDate(points[0][0])}) a ${format(last)} (${longDate(points[n - 1][0])})${changePct ? `, ${changePct}% no período` : ""}`
    : `${label}: sem dados`;

  const wrap = h("div", {
    class: `chart${compact ? " compact" : ""}`,
    role: "img",
    "aria-label": summary,
    tabindex: compact ? null : 0,
  });
  const tip = h("div", { class: "chart-tip", hidden: true }, h("strong"), h("span"));
  let geometry = null;
  let current = null;

  function draw() {
    const W = Math.max(120, Math.round(wrap.clientWidth || 300));
    const H = height || (compact ? 44 : 240);
    wrap.style.height = `${H}px`;
    const root = svg("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" });
    if (!n) {
      root.append(svgText({ x: W / 2, y: H / 2, "text-anchor": "middle", class: "axis" }, "sem dados"));
      wrap.replaceChildren(root);
      return;
    }
    const vals = points.map((p) => p[1]);
    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    let ticks = [];
    let axisFormat = format;
    if (compact) {
      if (lo === hi) { lo -= 1; hi += 1; }
    } else {
      const nice = niceTicks(lo, hi, 4);
      ({ ticks, lo, hi } = nice);
      const digits = stepDecimals(nice.step);
      // Eixo enxuto: "150 mil" em vez de "150.000" (os valores exatos ficam na dica e na tabela).
      const nf = Math.max(Math.abs(lo), Math.abs(hi)) >= 10000
        ? new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 })
        : new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
      axisFormat = (v) => nf.format(v);
    }
    const endText = !compact && compactFormat && W < 560 ? compactFormat(last) : format(last);
    // Espaço para os rótulos: medido pelo maior texto (fonte mono ≈ 7px por caractere).
    const yLabelW = compact ? 0 : Math.max(...ticks.map((t) => axisFormat(t).length)) * 7 + 10;
    const endLabelW = compact ? 0 : endText.length * 7.4 + 14;
    const padL = compact ? 2 : yLabelW;
    const padR = compact ? 7 : endLabelW;
    const padT = compact ? 7 : 12;
    const padB = compact ? 7 : 26;
    const plotW = Math.max(10, W - padL - padR);
    const plotH = Math.max(10, H - padT - padB);
    const x = (i) => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const y = (v) => padT + (1 - (v - lo) / (hi - lo || 1)) * plotH;

    if (!compact) {
      for (const t of ticks) {
        root.append(svg("line", { class: "grid", x1: padL, x2: padL + plotW, y1: y(t), y2: y(t) }));
        root.append(svgText({ class: "axis", x: padL - 8, y: y(t) + 4, "text-anchor": "end" }, axisFormat(t)));
      }
      const labels = Math.min(n, Math.max(2, Math.min(5, Math.floor(plotW / 72))));
      const seen = new Set();
      for (let k = 0; k < labels; k++) {
        const i = labels === 1 ? 0 : Math.round((k / (labels - 1)) * (n - 1));
        if (seen.has(i)) continue;
        seen.add(i);
        const anchor = k === 0 ? "start" : k === labels - 1 ? "end" : "middle";
        root.append(svgText({ class: "axis", x: x(i), y: H - 6, "text-anchor": anchor }, shortDate(points[i][0])));
      }
    }

    const line = points.map(([, v], i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const base = (padT + plotH).toFixed(1);
    root.append(svg("path", { class: "area", d: `${line}L${x(n - 1).toFixed(1)},${base}L${x(0).toFixed(1)},${base}Z` }));
    root.append(svg("path", { class: "line", d: line }));
    root.append(svg("circle", { class: "end", cx: x(n - 1), cy: y(last), r: 4 }));
    if (!compact) root.append(svgText({ class: "end-label", x: x(n - 1) + 9, y: y(last) + 4 }, endText));

    const cross = svg("line", { class: "cross", y1: padT, y2: padT + plotH, visibility: "hidden" });
    const crossDot = svg("circle", { class: "cross-dot", r: 4, visibility: "hidden" });
    // Área de captura = todo o gráfico (maior que a marca): o cursor só precisa chegar perto.
    const hit = svg("rect", { class: "hit", x: 0, y: 0, width: W, height: H });
    root.append(cross, crossDot, hit);
    wrap.replaceChildren(root, tip);
    geometry = { x, y, padL, plotW, W, cross, crossDot };
    if (current !== null) show(current);
  }

  function indexAt(clientX) {
    const rect = wrap.getBoundingClientRect();
    const px = clientX - rect.left;
    if (n === 1) return 0;
    return Math.max(0, Math.min(n - 1, Math.round(((px - geometry.padL) / geometry.plotW) * (n - 1))));
  }

  function show(i) {
    if (!geometry || !n) return;
    current = i;
    const [date, value] = points[i];
    const { x, y, cross, crossDot, W } = geometry;
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    crossDot.setAttribute("cx", x(i));
    crossDot.setAttribute("cy", y(value));
    cross.setAttribute("visibility", "visible");
    crossDot.setAttribute("visibility", "visible");
    tip.firstChild.textContent = format(value);
    tip.lastChild.textContent = longDate(date);
    tip.hidden = false;
    const tipW = tip.offsetWidth || 110;
    const left = x(i) + 12 + tipW > W ? x(i) - 12 - tipW : x(i) + 12;
    tip.style.left = `${Math.max(0, left)}px`;
    tip.style.top = compact ? "-6px" : "4px";
  }

  function hide() {
    current = null;
    tip.hidden = true;
    if (!geometry) return;
    geometry.cross.setAttribute("visibility", "hidden");
    geometry.crossDot.setAttribute("visibility", "hidden");
  }

  wrap.addEventListener("pointermove", (e) => { if (geometry && n) show(indexAt(e.clientX)); });
  wrap.addEventListener("pointerleave", hide);
  if (!compact) {
    wrap.addEventListener("focus", () => show(current ?? n - 1));
    wrap.addEventListener("blur", hide);
    wrap.addEventListener("keydown", (e) => {
      if (!n) return;
      const step = { ArrowLeft: -1, ArrowRight: 1, PageDown: -10, PageUp: 10 }[e.key];
      if (step) show(Math.max(0, Math.min(n - 1, (current ?? n - 1) + step)));
      else if (e.key === "Home") show(0);
      else if (e.key === "End") show(n - 1);
      else return;
      e.preventDefault();
    });
  }

  const observer = new ResizeObserver(() => {
    if (!wrap.isConnected) return;
    draw();
  });
  observer.observe(wrap);
  return wrap;
}

/** Tabela equivalente ao gráfico (acessível e sem depender de passar o mouse). */
export function chartTable({ dates = [], values = [], format = String, caption = "" }) {
  const rows = values.map((v, i) => h("tr", {}, h("td", { class: "mono" }, longDate(dates[i])), h("td", { class: "mono num" }, format(v))));
  return h("details", { class: "chart-table" },
    h("summary", {}, "Ver tabela"),
    h("div", { class: "table-wrap" },
      h("table", { class: "data" }, caption ? h("caption", {}, caption) : null,
        h("thead", {}, h("tr", {}, h("th", {}, "Data"), h("th", { class: "num" }, "Fechamento"))),
        h("tbody", {}, rows.reverse()))));
}
