// Mundo: resumo do dia, clima, mercado, indicadores, notícias, tendências e alertas.
//
// Tudo vem de /api/intel/* (o servidor guarda em cache e marca a fonte e o horário).
// Conteúdo da internet é DADO: sempre inserido com textContent (via h()) e links só http(s).

import { api } from "../api.js";
import { chartTable, lineChart } from "../charts.js";
import { renderMarkdown } from "../markdown.js";
import { on, state } from "../state.js";
import { fill, fmt, h, toast } from "../ui.js";

const PERIODS = [["1mo", "1 mês"], ["3mo", "3 meses"], ["6mo", "6 meses"], ["1y", "1 ano"]];
const QUOTES_REFRESH_MS = 2 * 60 * 1000;

// --- Formatação ------------------------------------------------------------------------

/**
 * Formata preços conforme o tipo do ativo (índice em pontos; moeda/ação/cripto com moeda).
 * Valores grandes (≥ 10 mil) ficam sem centavos; ``compact`` usa "R$ 400,2 mil" (telas estreitas).
 */
export function priceFormatter(kind, currency, { compact = false } = {}) {
  return (value) => {
    const v = Number(value);
    if (value === null || value === undefined || !Number.isFinite(v)) return "—";
    const abs = Math.abs(v);
    const digits = kind === "indice" || abs >= 10000 ? 0 : abs < 1 ? 4 : 2;
    const opts = compact && abs >= 10000
      ? { notation: "compact", maximumFractionDigits: 1 }
      : { minimumFractionDigits: digits, maximumFractionDigits: digits };
    if (kind !== "indice" && currency) {
      try { return new Intl.NumberFormat("pt-BR", { style: "currency", currency, ...opts }).format(v); } catch { /* moeda desconhecida */ }
    }
    return `${new Intl.NumberFormat("pt-BR", opts).format(v)}${kind === "indice" ? " pts" : ""}`;
  };
}

const num = (v, digits = 2) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);

function delta(pct, suffix = "hoje") {
  if (pct === null || pct === undefined || !Number.isFinite(Number(pct))) return h("span", { class: "delta flat" }, "—");
  const v = Number(pct);
  const dir = v > 0.004 ? "up" : v < -0.004 ? "down" : "flat";
  const icon = dir === "up" ? "▲" : dir === "down" ? "▼" : "■";
  const word = dir === "up" ? "alta" : dir === "down" ? "queda" : "estável";
  return h("span", { class: `delta ${dir}`, title: `${word} de ${num(Math.abs(v))}% ${suffix}` },
    h("span", { "aria-hidden": "true" }, icon), ` ${v > 0 ? "+" : ""}${num(v)}% `, h("small", {}, suffix));
}

/** Só aceita links http(s) — feeds são dados externos e não podem injetar javascript:. */
export function safeUrl(link) {
  try {
    const url = new URL(link);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch { return null; }
}

const WEEKDAY = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit" });
function dayName(iso, index) {
  if (index === 0) return "Hoje";
  if (index === 1) return "Amanhã";
  const [y, m, d] = iso.split("-").map(Number);
  return WEEKDAY.format(new Date(y, m - 1, d)).replace(".", "");
}

/** "há 5 min" / "agora". */
function since(iso) {
  const ago = fmt.ago(iso);
  return !ago || ago === "agora" ? ago : `há ${ago}`;
}

function updated(data, source) {
  if (!data) return null;
  return h("p", { class: "source" },
    source ? `Fonte: ${source}` : null,
    data.fetched_at ? `${source ? " · " : ""}atualizado ${fmt.time(data.fetched_at)}` : null,
    data.stale ? h("span", { class: "tag amber", title: "A fonte não respondeu; mostrando a última versão salva." }, "dados antigos") : null);
}

function failure(data, what) {
  return h("p", { class: "empty" }, `Não consegui carregar ${what}: ${data?.error || "fonte indisponível"}.`);
}

// --- Tela ------------------------------------------------------------------------------

export function mount(root) {
  const page = h("div", { class: "page world" });
  const card = (title, span, extra = null) => {
    const body = h("div", { class: "panel-body" });
    const head = h("div", { class: "panel-head" }, h("span", { class: "grow" }, title), extra);
    const el = h("section", { class: `panel ${span}` }, head, body);
    return { el, body, head };
  };

  const refreshBtn = h("button", { class: "btn", type: "button", onclick: () => load(true) }, "Atualizar");
  const stamp = h("span", { class: "hint" });
  const briefing = card("Resumo do dia", "span-7");
  const weather = card("Clima", "span-5");
  const market = card("Mercado — sua lista", "span-12");
  const detail = card("Histórico", "span-8");
  const indicators = card("Indicadores oficiais", "span-4");
  const news = card("Notícias", "span-8");
  const trends = card("Em alta no Brasil", "span-4");
  const alerts = card("Alertas", "span-12");

  page.append(
    h("h1", { class: "page-title" }, "Mundo"),
    h("div", { class: "toolbar" }, refreshBtn, stamp,
      h("span", { class: "hint grow-right" }, "Dados informativos, com fonte e horário. Cotações podem ter atraso; nada aqui é recomendação de investimento.")),
    h("div", { class: "grid" }, briefing.el, weather.el, market.el, detail.el, indicators.el, news.el, trends.el, alerts.el),
  );
  root.append(page);
  fill(detail.body, h("p", { class: "hint" }, "Carregando…"));

  let overview = null;
  let histories = {};
  let selected = null;
  let period = "3mo";
  let newsTab = null;
  let newsQuery = "";
  let generating = false;
  let alive = true;
  const timers = [];

  // --- Carregamento -------------------------------------------------------------------
  async function load(manual = false) {
    page.classList.add("refreshing");
    refreshBtn.disabled = true;
    try {
      overview = await api("/api/intel/overview");
      if (!alive) return;
      stamp.textContent = `Atualizado às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
      renderBriefing();
      renderWeather();
      detail.loadedFor = null;
      renderMarket();
      renderIndicators();
      renderNews();
      renderTrends();
      loadAlerts();
      loadHistories();
      if (manual) toast("Informações atualizadas.", "good", 2500);
    } catch (err) {
      toast(`Falha ao carregar: ${err.message}`, "bad");
    } finally {
      page.classList.remove("refreshing");
      refreshBtn.disabled = false;
    }
  }

  async function refreshQuotes() {
    try {
      const quotes = await api("/api/intel/quotes");
      if (!alive || !overview) return;
      overview.quotes = quotes;
      renderMarket();
    } catch { /* mantém o último quadro */ }
  }

  async function loadHistories() {
    try {
      histories = await api("/api/intel/histories?period=1mo");
      if (alive) renderMarket();
    } catch { /* minilinhas são opcionais */ }
  }

  // --- Resumo do dia --------------------------------------------------------------------
  function renderBriefing() {
    const b = overview?.briefing;
    const genBtn = h("button", { class: "btn small primary", type: "button", disabled: generating, onclick: generate },
      generating ? "Gerando…" : "Gerar agora");
    fill(briefing.head, h("span", { class: "grow" }, "Resumo do dia"),
      b ? h("span", { class: "hint" }, `${b.kind} · ${fmt.time(b.ts)}`) : null, genBtn);
    if (!b) {
      fill(briefing.body, h("p", { class: "empty" },
        "Nenhum resumo ainda. Os resumos automáticos saem nos horários definidos em Configurações → Informações; ou clique em “Gerar agora”."));
      return;
    }
    const text = h("div", { class: "md briefing-text collapsed" });
    text.innerHTML = renderMarkdown(b.text); // markdown.js escapa todo o conteúdo
    const toggle = h("button", { class: "btn ghost small", type: "button" }, "Ler tudo");
    toggle.addEventListener("click", () => {
      const open = text.classList.toggle("collapsed");
      toggle.textContent = open ? "Ler tudo" : "Recolher";
    });
    fill(briefing.body, text, toggle);
  }

  async function generate() {
    generating = true;
    renderBriefing();
    try {
      await api("/api/briefings", { method: "POST" });
      toast("Preparando o resumo… aviso quando ficar pronto.", "info");
      timers.push(setTimeout(() => { if (generating) { generating = false; renderBriefing(); } }, 180000));
    } catch (err) {
      generating = false;
      renderBriefing();
      toast(err.message, "bad");
    }
  }

  async function loadBriefing() {
    try {
      const [latest] = await api("/api/briefings?limit=1");
      if (!alive || !overview) return;
      overview.briefing = latest || null;
      generating = false;
      renderBriefing();
    } catch { /* tenta no próximo evento */ }
  }

  // --- Clima ---------------------------------------------------------------------------
  function renderWeather() {
    const w = overview?.weather;
    if (!w) {
      const input = h("input", { type: "text", placeholder: "Ex.: São Paulo", maxlength: 80, "aria-label": "Sua cidade" });
      const save = async (e) => {
        e.preventDefault();
        const city = input.value.trim();
        if (!city) return;
        try {
          await api("/api/settings", { method: "PUT", body: { city } });
          if (state.settings) state.settings.runtime.city = city;
          load();
        } catch (err) { toast(err.message, "bad"); }
      };
      fill(weather.head, h("span", { class: "grow" }, "Clima"));
      fill(weather.body, h("p", { class: "hint" }, "Informe sua cidade para ver o clima e receber avisos de chuva forte, calor e vento."),
        h("form", { class: "inline-form", onsubmit: save }, input, h("button", { class: "btn primary", type: "submit" }, "Salvar")));
      return;
    }
    if (w.error) {
      fill(weather.head, h("span", { class: "grow" }, `Clima — ${overview.city || ""}`));
      fill(weather.body, failure(w, "o clima"));
      return;
    }
    const place = [w.place.name, w.place.admin1].filter(Boolean).join(", ");
    fill(weather.head, h("span", { class: "grow" }, `Clima — ${place}`));
    const c = w.current || {};
    const days = w.daily || [];
    const tmin = Math.min(...days.map((d) => d.tmin ?? Infinity));
    const tmax = Math.max(...days.map((d) => d.tmax ?? -Infinity));
    const span = tmax - tmin || 1;
    const rows = days.map((d, i) => {
      const ok = Number.isFinite(span) && d.tmin != null && d.tmax != null;
      const left = ok ? ((d.tmin - tmin) / span) * 100 : 0;
      const width = ok ? Math.max(4, ((d.tmax - d.tmin) / span) * 100) : 0;
      return h("tr", {},
        h("th", { scope: "row" }, dayName(d.date, i), h("span", { class: "desc" }, d.desc || "")),
        h("td", { class: "rain", title: "Chuva prevista (mm) e chance máxima" },
          d.rain_mm != null ? `${num(d.rain_mm, 0)} mm` : "—", d.rain_prob != null ? h("small", {}, ` ${d.rain_prob}%`) : null),
        h("td", { class: "num" }, d.tmin != null ? `${Math.round(d.tmin)}°` : "—"),
        h("td", { class: "range", "aria-hidden": "true" },
          h("span", { class: "track" }, h("span", { class: "fill", style: { left: `${left}%`, width: `${width}%` } }))),
        h("td", { class: "num" }, d.tmax != null ? `${Math.round(d.tmax)}°` : "—"));
    });
    fill(weather.body,
      h("div", { class: "weather-now" },
        h("div", { class: "temp" }, c.temp != null ? `${Math.round(c.temp)}°` : "—"),
        h("div", {},
          h("div", { class: "now-desc" }, c.desc || ""),
          h("div", { class: "hint" },
            [c.feels_like != null ? `sensação ${Math.round(c.feels_like)}°` : null,
              c.humidity != null ? `umidade ${c.humidity}%` : null,
              c.wind != null ? `vento ${Math.round(c.wind)} km/h` : null].filter(Boolean).join(" · ")))),
      (w.risks || []).length
        ? h("ul", { class: "risks" }, w.risks.map((r) => h("li", {}, h("span", { class: "risk-icon", "aria-hidden": "true" }, "⚠"), h("span", {}, r),
          h("span", { class: "tag amber" }, "estimativa"))))
        : null,
      h("div", { class: "table-wrap" },
        h("table", { class: "forecast" },
          h("caption", { class: "sr-only" }, "Previsão para os próximos dias"),
          h("thead", { class: "sr-only" }, h("tr", {}, ["Dia e tempo", "Chuva", "Mínima", "Faixa", "Máxima"].map((t) => h("th", { scope: "col" }, t)))),
          h("tbody", {}, rows))),
      updated(w, w.source));
  }

  // --- Mercado -------------------------------------------------------------------------
  function orderedQuotes() {
    const q = overview?.quotes;
    if (!q || q.error) return [];
    const watch = (state.settings?.runtime?.watchlist || []).map((s) => s.toLowerCase());
    const rank = (s) => { const i = watch.indexOf(String(s).toLowerCase()); return i < 0 ? 999 : i; };
    return [...q.quotes].sort((a, b) => rank(a.symbol) - rank(b.symbol));
  }

  function renderMarket() {
    const q = overview?.quotes;
    if (!q || q.error) {
      fill(market.body, failure(q, "as cotações"));
      return;
    }
    const quotes = orderedQuotes();
    if (!selected && quotes.length) selected = quotes[0].symbol;
    const tiles = quotes.map((quote) => {
      const format = priceFormatter(quote.kind, quote.currency);
      const hist = histories[quote.symbol];
      const spark = hist && !hist.error && hist.closes?.length > 1
        ? lineChart({ dates: hist.dates, values: hist.closes, format, label: `${quote.label}, último mês`, compact: true })
        : h("div", { class: "chart compact placeholder" });
      const isOn = selected === quote.symbol;
      return h("div", { class: `tile${isOn ? " on" : ""}`, onclick: () => select(quote.symbol) },
        h("button", { class: "tile-head", type: "button", title: quote.label, "aria-pressed": String(isOn), onclick: (e) => { e.stopPropagation(); select(quote.symbol); } },
          h("span", { class: "tile-label" }, quote.label)),
        h("div", { class: "tile-value" }, format(quote.price)),
        delta(quote.change_pct, quote.kind === "cripto" ? "24 h" : "hoje"),
        spark,
        h("div", { class: "tile-foot", title: quote.source }, h("span", { class: "tag" }, quote.symbol.toUpperCase()), quote.time ? ` às ${fmt.time(quote.time)}` : ""));
    });
    fill(market.body,
      tiles.length ? h("div", { class: "tiles" }, tiles) : h("p", { class: "empty" }, "Nenhuma cotação disponível."),
      (q.errors || []).length ? h("p", { class: "hint" }, `Sem dados para: ${q.errors.join("; ")}`) : null,
      h("p", { class: "source" },
        "Fontes: Yahoo Finance (B3 com ~15 min de atraso), AwesomeAPI (moedas), CoinGecko (cripto)",
        q.fetched_at ? ` · consultado ${fmt.time(q.fetched_at)}` : null,
        q.stale ? h("span", { class: "tag amber" }, "dados antigos") : null,
        " · Edite a lista em Configurações → Informações."));
    if (selected && !detail.loadedFor) loadDetail();
  }

  function select(symbol) {
    if (selected === symbol) return;
    selected = symbol;
    renderMarket();
    loadDetail();
  }

  async function loadDetail() {
    const quote = orderedQuotes().find((q) => q.symbol === selected);
    if (!quote) return;
    const key = `${selected}:${period}`;
    detail.loadedFor = key;
    detail.el.classList.add("refreshing");
    let data;
    try {
      data = await api(`/api/intel/history?symbol=${encodeURIComponent(selected)}&period=${period}`);
    } catch (err) {
      data = { error: err.message };
    }
    if (!alive || detail.loadedFor !== key) return;
    detail.el.classList.remove("refreshing");
    renderDetail(quote, data);
  }

  function renderDetail(quote, data) {
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Período" }, PERIODS.map(([v, label]) => h("button", {
      type: "button", class: v === period ? "on" : "", "aria-pressed": String(v === period),
      onclick: () => { if (period !== v) { period = v; loadDetail(); } },
    }, label)));
    fill(detail.head, h("span", { class: "grow" }, `Histórico — ${quote.label}`), seg);
    if (data.error) {
      fill(detail.body, failure(data, "o histórico"));
      return;
    }
    const format = priceFormatter(quote.kind, quote.currency);
    const s = data.stats || {};
    const periodLabel = PERIODS.find(([v]) => v === period)?.[1] || period;
    const stat = (label, value, help) => h("div", { title: help || null }, h("dt", {}, label), h("dd", {}, value));
    fill(detail.body,
      lineChart({ dates: data.dates, values: data.closes, format, compactFormat: priceFormatter(quote.kind, quote.currency, { compact: true }), label: `${quote.label}, ${periodLabel}` }),
      h("dl", { class: "stats" },
        stat("Variação", s.change_period_pct != null ? `${s.change_period_pct > 0 ? "+" : ""}${num(s.change_period_pct)}%` : "—", `Do primeiro ao último fechamento (${periodLabel}).`),
        stat("Mínima", format(s.min)),
        stat("Máxima", format(s.max)),
        stat("Volatilidade", s.volatility_annual_pct != null ? `${num(s.volatility_annual_pct)}%` : "—", "Desvio-padrão dos retornos diários, anualizado: quanto o preço costuma oscilar."),
        stat("Maior queda", s.max_drawdown_pct != null ? `${num(s.max_drawdown_pct)}%` : "—", "Maior queda de um pico até um vale dentro do período."),
        stat("Tendência", s.trend || "—")),
      h("p", { class: "hint" }, s.note || "Estimativas técnicas sobre o histórico; não são previsões nem recomendação."),
      chartTable({ dates: data.dates, values: data.closes, format, caption: `${quote.label} — fechamentos (${periodLabel})` }),
      updated(data, data.source));
  }

  // --- Indicadores -----------------------------------------------------------------------
  function renderIndicators() {
    const ind = overview?.indicators;
    if (!ind || ind.error) {
      fill(indicators.body, failure(ind, "os indicadores"));
      return;
    }
    const value = (i) => (String(i.unit).startsWith("R$") ? `R$ ${num(i.value, 4)}` : `${num(i.value)}${String(i.unit).startsWith("%") ? "" : " "}${i.unit}`);
    fill(indicators.body,
      h("ul", { class: "indicators" }, ind.items.map((i) => h("li", {},
        h("span", { class: "ind-name" }, i.name),
        i.error
          ? h("span", { class: "hint" }, "indisponível")
          : [h("span", { class: "ind-value" }, value(i)),
            h("span", { class: "ind-meta" }, `em ${i.date}`, i.previous != null ? ` · anterior ${num(i.previous, String(i.unit).startsWith("R$") ? 4 : 2)}` : null)]))),
      updated(ind, "Banco Central do Brasil — SGS (oficial)"));
  }

  // --- Notícias ----------------------------------------------------------------------------
  function newsList(data) {
    if (!data || data.error) return failure(data, "as notícias");
    if (!data.items?.length) return h("p", { class: "empty" }, "Nenhuma notícia encontrada.");
    return h("ul", { class: "news" }, data.items.map((item) => {
      const href = safeUrl(item.link);
      const title = href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, item.title) : h("span", {}, item.title);
      return h("li", {},
        h("div", { class: "news-title" }, title),
        h("div", { class: "news-meta" }, item.source, item.published ? ` · ${since(item.published)}` : ""),
        item.summary && item.summary !== item.title ? h("p", { class: "news-sum" }, item.summary) : null);
    }));
  }

  function renderNews() {
    const categories = overview?.categories || {};
    const topics = Object.keys(overview?.news || {});
    if (!newsTab) newsTab = topics[0] || "brasil";
    const ordered = [...topics, ...Object.keys(categories).filter((c) => !topics.includes(c))];
    const tabs = h("div", { class: "seg tabs", role: "group", "aria-label": "Categoria" }, ordered.map((c) => h("button", {
      type: "button", class: !newsQuery && c === newsTab ? "on" : "", "aria-pressed": String(!newsQuery && c === newsTab),
      onclick: () => { newsQuery = ""; newsTab = c; renderNews(); },
    }, categories[c] || c)));
    const search = h("input", { type: "search", placeholder: "Procurar notícias…", value: newsQuery, "aria-label": "Procurar notícias", maxlength: 120 });
    const form = h("form", { class: "inline-form", onsubmit: (e) => { e.preventDefault(); newsQuery = search.value.trim(); renderNews(); } },
      search, h("button", { class: "btn", type: "submit" }, "Buscar"));
    const listBox = h("div", { class: "news-box" });
    fill(news.body, h("div", { class: "news-controls" }, tabs, form), listBox);

    const cached = !newsQuery && overview?.news?.[newsTab];
    if (cached && !cached.error) {
      fill(listBox, newsList(cached), updated(cached, (cached.sources || []).join(", ")));
      return;
    }
    fill(listBox, h("p", { class: "hint" }, "Carregando…"));
    const url = newsQuery ? `/api/intel/news?q=${encodeURIComponent(newsQuery)}&limit=15` : `/api/intel/news?category=${encodeURIComponent(newsTab)}&limit=15`;
    const wanted = `${newsQuery}|${newsTab}`;
    api(url).then((data) => {
      if (!alive || wanted !== `${newsQuery}|${newsTab}`) return;
      fill(listBox, newsList(data), updated(data, data.source || (data.sources || []).join(", ")));
    }).catch((err) => { if (alive) fill(listBox, failure({ error: err.message }, "as notícias")); });
  }

  // --- Tendências ----------------------------------------------------------------------------
  function renderTrends() {
    const t = overview?.trends;
    if (!t || t.error) {
      fill(trends.body, failure(t, "as tendências"));
      return;
    }
    fill(trends.body,
      t.items.length
        ? h("ol", { class: "trends" }, t.items.map((item) => h("li", {},
          h("span", { class: "grow" }, item.title),
          item.traffic ? h("span", { class: "tag", title: "Buscas aproximadas" }, item.traffic) : null)))
        : h("p", { class: "empty" }, "Sem tendências agora."),
      updated(t, t.source));
  }

  // --- Alertas -------------------------------------------------------------------------------
  let alertData = null;
  const form = { kind: "preco_acima" };
  const formBox = h("div");
  const listBox = h("div");
  fill(alerts.body, h("div", { class: "alerts-layout" }, formBox, listBox));

  async function loadAlerts() {
    try {
      const first = !alertData;
      alertData = await api("/api/alerts");
      if (!alive) return;
      if (first) renderAlertForm();
      renderAlerts();
    } catch (err) { if (alive) fill(listBox, failure({ error: err.message }, "os alertas")); }
  }

  function renderAlertForm() { fill(formBox, alertForm()); }

  function alertForm() {
    const kinds = alertData?.kinds || {};
    const watch = state.settings?.runtime?.watchlist || [];
    const field = (label, input, hint) => h("label", { class: "field" }, label, input, hint ? h("small", { class: "hint" }, hint) : null);
    const input = (key, attrs) => {
      const el = h("input", { ...attrs, value: form[key] ?? "" });
      el.addEventListener("input", () => { form[key] = el.value; });
      return el;
    };
    const kindSelect = h("select", { "aria-label": "Tipo de alerta" },
      Object.entries(kinds).map(([k, label]) => h("option", { value: k, selected: k === form.kind }, label)));
    kindSelect.addEventListener("change", () => { form.kind = kindSelect.value; renderAlertForm(); });
    const symbolList = h("datalist", { id: "watch-symbols" }, watch.map((s) => h("option", { value: s })));
    const specific = {
      preco_acima: [field("Ativo", input("symbol", { type: "text", list: "watch-symbols", required: true, placeholder: "PETR4, BTC, USD…" })),
        field("Valor", input("value", { type: "number", step: "any", required: true }))],
      variacao: [field("Ativo", input("symbol", { type: "text", list: "watch-symbols", required: true, placeholder: "IBOV" })),
        field("Variação (%)", input("pct", { type: "number", step: "0.1", min: "0.1", placeholder: "3" }))],
      noticia: [field("Palavras-chave", input("keywords", { type: "text", required: true, placeholder: "Selic, Petrobras, OpenAI" }), "Separe por vírgulas.")],
      clima: [field("Chuva (mm)", input("rain_mm", { type: "number", step: "1", placeholder: "30" })),
        field("Máxima (°C)", input("temp_max", { type: "number", step: "1", placeholder: "35" })),
        field("Mínima (°C)", input("temp_min", { type: "number", step: "1", placeholder: "5" })),
        field("Vento (km/h)", input("wind_kmh", { type: "number", step: "1", placeholder: "60" }))],
    };
    specific.preco_abaixo = specific.preco_acima;

    async function submit(e) {
      e.preventDefault();
      const params = {};
      for (const key of ["symbol", "value", "pct", "rain_mm", "temp_max", "temp_min", "wind_kmh"]) {
        if (form[key] !== undefined && String(form[key]).trim() !== "") params[key] = key === "symbol" ? String(form[key]).trim() : Number(form[key]);
      }
      if (form.kind === "noticia") params.keywords = String(form.keywords || "").split(",").map((k) => k.trim()).filter(Boolean);
      try {
        const created = await api("/api/alerts", { method: "POST", body: { kind: form.kind, params, label: form.label || "", cooldown_h: Number(form.cooldown_h || 6) } });
        toast(`Alerta criado: ${created.label}`, "good");
        for (const key of Object.keys(form)) if (key !== "kind") delete form[key];
        renderAlertForm();
        loadAlerts();
      } catch (err) { toast(err.message, "bad", 6000); }
    }

    return h("form", { class: "alert-form", onsubmit: submit },
      h("h3", {}, "Novo alerta"),
      field("Tipo", kindSelect),
      specific[form.kind] || null,
      symbolList,
      field("Descrição (opcional)", input("label", { type: "text", maxlength: 120, placeholder: "Gerada automaticamente" })),
      field("Intervalo mínimo entre avisos (horas)", input("cooldown_h", { type: "number", min: "0.1", max: "168", step: "0.5", placeholder: "6" })),
      form.kind.startsWith("preco") ? h("p", { class: "hint" }, "Alertas de preço desligam sozinhos depois de avisar.") : null,
      h("button", { class: "btn primary", type: "submit" }, "Criar alerta"));
  }

  function renderAlerts() {
    if (!alertData) return;
    const list = alertData.alerts.length
      ? h("ul", { class: "list alert-list" }, alertData.alerts.map((a) => {
        const sw = h("input", { type: "checkbox", checked: a.enabled, "aria-label": `Ativar alerta: ${a.label}` });
        sw.addEventListener("change", async () => {
          try { await api(`/api/alerts/${a.id}`, { method: "PATCH", body: { enabled: sw.checked } }); loadAlerts(); } catch (err) { toast(err.message, "bad"); }
        });
        return h("li", { class: a.enabled ? "" : "off" },
          h("label", { class: "switch" }, sw),
          h("span", { class: "grow", title: a.label }, a.label),
          h("span", { class: "tag" }, a.kind_label),
          a.last_triggered_at ? h("span", { class: "time" }, `avisou ${since(a.last_triggered_at)}`) : null,
          h("button", {
            class: "btn ghost small", type: "button", "aria-label": `Excluir alerta: ${a.label}`,
            onclick: async () => {
              if (!confirm(`Excluir o alerta “${a.label}”?`)) return;
              try { await api(`/api/alerts/${a.id}`, { method: "DELETE" }); loadAlerts(); } catch (err) { toast(err.message, "bad"); }
            },
          }, "Excluir"));
      }))
      : h("p", { class: "empty" }, "Nenhum alerta. Crie um ao lado ou peça no chat: “me avise se o dólar passar de 5,80”.");
    const events = alertData.events.length
      ? h("ul", { class: "list events" }, alertData.events.slice(0, 12).map((e) => h("li", {},
        h("span", { class: "risk-icon", "aria-hidden": "true" }, "🔔"),
        h("span", { class: "grow" }, h("strong", {}, e.title), h("span", { class: "hint" }, ` — ${e.message}`)),
        h("span", { class: "time" }, since(e.ts)))))
      : h("p", { class: "empty" }, "Nenhum aviso disparado ainda.");
    const check = h("button", {
      class: "btn small", type: "button",
      onclick: async () => {
        check.disabled = true;
        try {
          const res = await api("/api/alerts/check", { method: "POST" });
          toast(res.triggered.length ? `${res.triggered.length} alerta(s) disparado(s).` : "Nenhum alerta disparou agora.", "info");
          loadAlerts();
        } catch (err) { toast(err.message, "bad"); } finally { check.disabled = false; }
      },
    }, "Verificar agora");
    const notify = "Notification" in window && Notification.permission === "default"
      ? h("button", {
        class: "btn small ghost", type: "button",
        onclick: async () => { await Notification.requestPermission(); renderAlerts(); },
      }, "Ativar notificações do Windows")
      : null;
    fill(alerts.head, h("span", { class: "grow" }, "Alertas"), notify, check);
    fill(listBox, h("h3", {}, "Seus alertas"), list, h("h3", {}, "Avisos recentes"), events,
      h("p", { class: "hint" }, "Verificados a cada 5 minutos enquanto a Sexta-Feira estiver ligada. Avisos de clima são estimativas da previsão, não alertas oficiais da Defesa Civil."));
  }

  // --- Tempo real ------------------------------------------------------------------------------
  const offLive = on("live", (ev) => {
    if (ev.type === "alert" || ev.type === "alerts_changed") loadAlerts();
    if (ev.type === "briefing_ready") loadBriefing();
  });
  timers.push(setInterval(() => { if (!document.hidden) refreshQuotes(); }, QUOTES_REFRESH_MS));

  load();
  return () => {
    alive = false;
    offLive();
    timers.forEach((t) => { clearInterval(t); clearTimeout(t); });
  };
}
