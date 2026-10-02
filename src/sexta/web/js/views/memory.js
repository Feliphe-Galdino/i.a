// Memória: visualizar, buscar, criar, editar, fixar, exportar, importar e excluir.

import { api } from "../api.js";
import { on } from "../state.js";
import { clear, debounce, download, fill, fmt, h, toast } from "../ui.js";

export function mount(root) {
  let categories = {};
  let editing = null;

  const search = h("input", { type: "search", placeholder: "Buscar na memória…", "aria-label": "Buscar na memória" });
  const category = h("select", { "aria-label": "Categoria" }, h("option", { value: "" }, "Todas as categorias"));
  const fileInput = h("input", { type: "file", accept: "application/json,.json", class: "hidden" });
  const counter = h("span", { class: "hint" });
  const formSlot = h("div");
  const gridEl = h("div", { class: "mem-grid" });
  const semanticBar = h("div", { class: "semantic-bar panel" });
  let semantic = null;

  const page = h("div", { class: "page" },
    h("h1", { class: "page-title" }, "Memória de longo prazo"),
    h("p", { class: "hint", style: { marginTop: "-8px" } },
      "Tudo o que a Sexta-Feira aprendeu sobre você. Apenas memórias relevantes (e as fixadas) são enviadas à IA em cada conversa. A busca combina palavras e significado (calculado no seu PC)."),
    h("div", { class: "toolbar" }, search, category,
      h("button", { class: "btn primary", onclick: () => openForm(null) }, "+ Nova memória"),
      h("button", { class: "btn", onclick: exportAll }, "Exportar"),
      h("button", { class: "btn", onclick: () => fileInput.click() }, "Importar"),
      h("button", { class: "btn danger", onclick: wipe }, "Apagar tudo"),
      counter, fileInput),
    semanticBar,
    formSlot,
    gridEl);
  root.append(page);

  search.addEventListener("input", debounce(load, 200));
  category.addEventListener("change", load);
  fileInput.addEventListener("change", importFile);

  async function init() {
    try {
      const stats = await api("/api/memories/stats");
      categories = stats.categories;
      for (const [key, desc] of Object.entries(categories)) category.append(h("option", { value: key, title: desc }, `${key} (${stats.by_category[key] || 0})`));
    } catch (err) { toast(err.message, "bad"); }
    load();
  }

  async function load() {
    const params = new URLSearchParams({ limit: "500" });
    if (search.value.trim()) params.set("q", search.value.trim());
    if (category.value) params.set("category", category.value);
    try {
      const items = await api(`/api/memories?${params}`);
      counter.textContent = `${items.length} memória(s)`;
      fill(gridEl, items.length ? items.map(renderCard) : h("p", { class: "empty" },
        search.value || category.value ? "Nada encontrado." : "Ainda não há memórias. Converse com a Sexta-Feira ou adicione uma manualmente."));
    } catch (err) { toast(err.message, "bad"); }
    loadSemantic();
  }

  // --- Busca por significado (embeddings locais) ------------------------------------
  const SEMANTIC_LABEL = {
    ready: "ativa", loading: "carregando o modelo…", off: "aguardando", disabled: "desligada", unavailable: "indisponível",
  };

  async function loadSemantic() {
    try { semantic = await api("/api/memories/semantic"); } catch { semantic = null; }
    renderSemantic();
    if (semantic?.state === "loading") setTimeout(() => { if (semanticBar.isConnected) loadSemantic(); }, 2500);
  }

  function renderSemantic() {
    if (!semantic) return fill(semanticBar);
    const toggle = h("input", { type: "checkbox", checked: semantic.state !== "disabled", "aria-label": "Busca por significado" });
    toggle.addEventListener("change", async () => {
      try {
        await api("/api/settings", { method: "PUT", body: { semantic_memory: toggle.checked } });
        loadSemantic();
      } catch (err) { toast(err.message, "bad"); }
    });
    const ready = semantic.state === "ready";
    fill(semanticBar,
      h("label", { class: "switch" }, toggle, "Busca por significado"),
      h("span", { class: `tag ${ready ? "green" : semantic.state === "unavailable" ? "amber" : ""}` }, SEMANTIC_LABEL[semantic.state] || semantic.state),
      ready ? h("span", { class: "hint" }, `${semantic.indexed} de ${semantic.total} memórias indexadas`) : null,
      semantic.error ? h("span", { class: "hint grow" }, semantic.error) : h("span", { class: "grow" }),
      h("button", { class: "btn small", type: "button", disabled: semantic.state === "disabled" || semantic.state === "loading", onclick: reindex }, ready ? "Reindexar" : "Tentar carregar"),
      h("button", { class: "btn small", type: "button", disabled: !ready, onclick: findDuplicates, title: "Encontra memórias quase iguais para você mesclar" }, "Encontrar parecidas"));
  }

  async function reindex() {
    try { await api("/api/memories/semantic/reindex", { method: "POST" }); toast("Reindexando em segundo plano…", "info"); } catch (err) { toast(err.message, "bad"); }
    setTimeout(loadSemantic, 1200);
  }

  async function findDuplicates() {
    let data;
    try { data = await api("/api/memories/duplicates"); } catch (err) { return toast(err.message, "bad"); }
    if (!data.pairs.length) {
      clear(formSlot);
      return toast("Nenhuma memória repetida encontrada. 👌", "good");
    }
    const side = (keep, other) => h("div", { class: "dup-side" },
      h("p", {}, keep.content),
      h("div", { class: "row" }, h("span", { class: "tag cyan" }, keep.category), h("span", { class: "stars" }, "★".repeat(keep.importance)),
        h("button", { class: "btn small", type: "button", onclick: () => merge(keep, other) }, "Manter esta")));
    fill(formSlot, h("section", { class: "panel dup-panel" },
      h("div", { class: "panel-head" }, h("span", { class: "grow" }, `Memórias parecidas (${data.pairs.length})`),
        h("button", { class: "btn ghost small", type: "button", onclick: () => clear(formSlot) }, "Fechar")),
      h("div", { class: "panel-body" },
        h("p", { class: "hint" }, "Escolha qual texto manter: a outra é apagada e as tags, a importância e o “fixada” são somados. Confira antes — frases parecidas podem dizer coisas opostas (“gosto” × “não gosto”)."),
        data.pairs.map((p) => h("div", { class: "dup-pair" },
          side(p.a, p.b), h("div", { class: "dup-score", title: "Similaridade de significado" }, `${Math.round(p.similarity * 100)}%`), side(p.b, p.a))))));
  }

  async function merge(keep, remove) {
    try {
      await api("/api/memories/merge", { method: "POST", body: { keep_id: keep.id, remove_id: remove.id } });
      toast("Memórias mescladas.", "good");
      await load();
      findDuplicates();
    } catch (err) { toast(err.message, "bad"); }
  }

  function renderCard(m) {
    return h("article", { class: `mem-card panel ${m.pinned ? "pinned" : ""}` },
      h("div", { class: "content" }, m.content),
      h("div", { class: "row" },
        h("span", { class: "tag cyan" }, m.category),
        m.pinned ? h("span", { class: "tag amber" }, "fixada") : null,
        m.tags.map((t) => h("span", { class: "tag" }, `#${t}`)),
        h("span", { class: "stars", title: `Importância ${m.importance}/5` }, "★".repeat(m.importance) + "☆".repeat(5 - m.importance))),
      h("div", { class: "row" },
        h("span", { class: "hint" }, `${m.source === "assistant" ? "aprendida pela IA" : m.source === "import" ? "importada" : "adicionada por você"} · ${fmt.time(m.updated_at)}${m.access_count ? ` · usada ${m.access_count}x` : ""}`),
        h("span", { class: "actions" },
          h("button", { class: "btn ghost small", title: m.pinned ? "Desafixar" : "Fixar (sempre no contexto)", onclick: () => patch(m.id, { pinned: !m.pinned }) }, m.pinned ? "Desafixar" : "Fixar"),
          h("button", { class: "btn ghost small", onclick: () => openForm(m) }, "Editar"),
          h("button", { class: "btn ghost small", onclick: () => remove(m) }, "Excluir"))));
  }

  function openForm(memory) {
    editing = memory;
    const content = h("textarea", { rows: 3, maxlength: 2000, placeholder: "Ex.: Prefiro respostas em tópicos, com exemplos de código em Python." }, memory?.content || "");
    const cat = h("select", {}, Object.keys(categories).map((k) => h("option", { value: k, selected: (memory?.category || "geral") === k }, k)));
    const tags = h("input", { type: "text", placeholder: "tags separadas por vírgula", value: memory?.tags.join(", ") || "" });
    const importance = h("input", { type: "number", min: 1, max: 5, value: memory?.importance || 3 });
    const pinned = h("input", { type: "checkbox", checked: memory?.pinned || false });
    const save = async (e) => {
      e.preventDefault();
      const body = {
        content: content.value.trim(),
        category: cat.value,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
        importance: Number(importance.value) || 3,
        pinned: pinned.checked,
      };
      if (!body.content) return toast("Escreva o conteúdo da memória.", "warn");
      try {
        if (editing) await api(`/api/memories/${editing.id}`, { method: "PATCH", body });
        else await api("/api/memories", { method: "POST", body });
        toast("Memória salva.", "good");
        clear(formSlot);
        load();
      } catch (err) { toast(err.message, "bad"); }
    };
    clear(formSlot).append(h("form", { class: "mem-form panel", onsubmit: save },
      h("label", { class: "field" }, memory ? `Editar memória #${memory.id}` : "Nova memória", content),
      h("div", { class: "cols" },
        h("label", { class: "field" }, "Categoria", cat),
        h("label", { class: "field" }, "Tags", tags),
        h("label", { class: "field" }, "Importância", importance),
        h("label", { class: "switch" }, pinned, "Fixar")),
      h("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } },
        h("button", { class: "btn ghost", type: "button", onclick: () => clear(formSlot) }, "Cancelar"),
        h("button", { class: "btn primary", type: "submit" }, "Salvar"))));
    content.focus();
  }

  async function patch(id, body) {
    try { await api(`/api/memories/${id}`, { method: "PATCH", body }); load(); } catch (err) { toast(err.message, "bad"); }
  }

  async function remove(m) {
    if (!confirm(`Excluir esta memória?\n\n“${m.content}”`)) return;
    try { await api(`/api/memories/${m.id}`, { method: "DELETE" }); load(); } catch (err) { toast(err.message, "bad"); }
  }

  async function exportAll() {
    try {
      const res = await api("/api/memories/export", { raw: true });
      download(`sexta-feira-memorias-${new Date().toISOString().slice(0, 10)}.json`, await res.text());
    } catch (err) { toast(err.message, "bad"); }
  }

  async function importFile() {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const result = await api("/api/memories/import", { method: "POST", body: data });
      toast(`Importação: ${result.created} novas, ${result.updated} atualizadas, ${result.skipped} ignoradas.`, "good", 6000);
      load();
    } catch (err) { toast(`Falha ao importar: ${err.message}`, "bad"); }
  }

  async function wipe() {
    const typed = prompt("Isso apaga TODAS as memórias de forma permanente.\nRecomendo exportar antes.\n\nDigite APAGAR TUDO para confirmar:");
    if (typed !== "APAGAR TUDO") return;
    try {
      const res = await api(`/api/memories?confirm=${encodeURIComponent("APAGAR TUDO")}`, { method: "DELETE" });
      toast(`${res.deleted} memória(s) apagada(s).`, "warn");
      load();
    } catch (err) { toast(err.message, "bad"); }
  }

  init();
  const offLive = on("live", (ev) => { if (ev.type === "memory_saved" || ev.type === "memory_deleted") load(); });
  return () => offLive();
}
