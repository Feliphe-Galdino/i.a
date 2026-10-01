// Configurações: perfil, autonomia, permissões, modelos, orçamento, internet e pastas.

import { api } from "../api.js";
import { refreshStatus } from "../app.js";
import { state } from "../state.js";
import { clear, h, riskTag, toast } from "../ui.js";

const PRIORITIES = [
  ["qualidade", "Qualidade", "Usa modelos e esforço maiores sempre que fizer sentido."],
  ["equilibrio", "Equilíbrio", "O MEGABRAIN pondera qualidade, velocidade e custo."],
  ["economia", "Economia", "Prefere modelos mais leves; tarefas muito complexas ainda vão para o Opus."],
];

export function mount(root) {
  const page = h("div", { class: "page" }, h("h1", { class: "page-title" }, "Configurações"));
  const body = h("div", { class: "settings" });
  page.append(body);
  root.append(page);
  let data = null;
  let draft = null;

  async function load() {
    try {
      data = await api("/api/settings");
      state.settings = data;
      draft = structuredClone(data.runtime);
      render();
    } catch (err) { toast(err.message, "bad"); }
  }

  const section = (title, ...children) => h("section", { class: "panel" }, h("div", { class: "panel-head" }, title), h("div", { class: "panel-body" }, ...children));
  const bind = (key, input, parse = (v) => v) => {
    const update = () => { draft[key] = parse(input.type === "checkbox" ? input.checked : input.value); };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
    return input;
  };

  function render() {
    const rt = draft;
    // --- Perfil
    const profile = section("Perfil",
      h("div", { class: "form-grid" },
        h("label", { class: "field" }, "Seu nome", bind("user_name", h("input", { type: "text", value: rt.user_name, maxlength: 80, placeholder: "Como devo chamar você?" }))),
        h("label", { class: "field" }, "Nome da assistente", bind("assistant_name", h("input", { type: "text", value: rt.assistant_name, maxlength: 40 })))),
      h("label", { class: "field" }, "Instruções personalizadas",
        bind("custom_instructions", h("textarea", { rows: 4, maxlength: 4000, placeholder: "Ex.: Sou estudante de Engenharia de Software. Explique com analogias e sempre sugira próximos passos." }, rt.custom_instructions))),
      h("p", { class: "hint" }, "O perfil e as instruções valem para novas conversas (cada conversa congela seu prompt para manter o cache e a coerência)."));

    // --- Autonomia
    const levels = h("div", { class: "levels" }, Object.entries(data.autonomy_levels).map(([level, info]) => h("button", {
      type: "button", class: `level l${level} ${Number(level) === rt.autonomy_level ? "on" : ""}`,
      onclick: () => { draft.autonomy_level = Number(level); render(); },
    }, h("strong", {}, `${level} · ${info.name}`), h("span", {}, info.description))));
    const autonomy = section("Nível de autonomia", levels,
      h("p", { class: "hint" }, "Ações críticas (excluir arquivos, encerrar processos, comandos destrutivos) SEMPRE pedem confirmação. Comandos catastróficos são sempre bloqueados."));

    // --- Permissões
    const permRows = Object.entries(data.capabilities).map(([cap, label]) => {
      const current = rt.permission_overrides[cap] || "";
      const seg = h("div", { class: "seg" }, [["", "Padrão"], ["allow", "Permitir"], ["ask", "Perguntar"], ["deny", "Negar"]].map(([v, l]) => h("button", {
        type: "button", "data-v": v, class: current === v ? "on" : "",
        onclick: () => { if (v) draft.permission_overrides[cap] = v; else delete draft.permission_overrides[cap]; render(); },
      }, l)));
      const tools = data.tools.filter((t) => t.capability === cap);
      return h("div", { class: "perm-row" },
        h("div", { class: "info" }, label, h("small", {}, `${cap} · ${tools.map((t) => t.name).join(", ") || "servidor"}`)),
        h("span", {}, tools.length ? riskTag(tools.map((t) => t.risk).sort(riskOrder).at(-1)) : null), seg);
    });
    const permissions = section("Permissões por capacidade", ...permRows,
      h("p", { class: "hint" }, "“Padrão” segue o nível de autonomia. “Negar” bloqueia a capacidade por completo."));

    // --- Modelos e roteamento
    const modelOptions = (tier) => {
      const current = rt.tier_models[tier] || "";
      const select = h("select", {}, h("option", { value: "" }, `Padrão (${data.tiers[tier].default_model})`),
        Object.entries(data.models).map(([id, m]) => h("option", { value: id, selected: current === id }, `${m.label} — US$ ${m.input}/${m.output} por MTok`)));
      select.addEventListener("change", () => { if (select.value) draft.tier_models[tier] = select.value; else delete draft.tier_models[tier]; });
      return h("label", { class: "field" }, `Camada ${data.tiers[tier].label}`, select);
    };
    const routing = section("MEGABRAIN — roteamento de modelos",
      h("div", { class: "levels" }, PRIORITIES.map(([v, l, d]) => h("button", {
        type: "button", class: `level ${rt.routing_priority === v ? "on" : ""}`, onclick: () => { draft.routing_priority = v; render(); },
      }, h("strong", {}, l), h("span", {}, d)))),
      h("div", { class: "form-grid" }, ["rapido", "equilibrado", "profundo"].map(modelOptions)),
      h("p", { class: "hint" }, "Dica: no chat, comece a mensagem com /rapido, /equilibrado ou /profundo para escolher manualmente."));

    // --- Orçamento e internet
    const budget = section("Orçamento e internet",
      h("div", { class: "form-grid" },
        h("label", { class: "field" }, "Orçamento diário (US$)", bind("daily_budget_usd", h("input", { type: "number", min: 0, step: 0.5, value: rt.daily_budget_usd }), Number)),
        h("label", { class: "switch" }, bind("budget_hard_stop", h("input", { type: "checkbox", checked: rt.budget_hard_stop })), "Bloquear chamadas ao atingir o orçamento"),
        h("label", { class: "switch" }, bind("web_search", h("input", { type: "checkbox", checked: rt.web_search })), "Permitir pesquisa na internet (US$ 0,01 por busca)")),
      h("p", { class: "hint" }, "Sem bloqueio, ao passar de 80% do orçamento o roteador limita a camada Equilibrado e, acima de 100%, usa apenas a Rápida."));

    // --- Pastas
    const rootInput = h("input", { type: "text", placeholder: "Ex.: C:\\Users\\voce\\Projetos  ou  /home/voce/projetos" });
    const rootsList = h("div", { class: "roots" },
      h("div", { class: "root" }, h("span", {}, data.paths.workspace), h("span", { class: "tag cyan" }, "pasta de trabalho")),
      data.paths.extra_roots.map((p) => h("div", { class: "root" }, h("span", {}, p), h("span", { class: "tag" }, ".env"))),
      rt.fs_roots.map((p, i) => h("div", { class: "root" }, h("span", {}, p),
        h("button", { class: "btn ghost small", type: "button", onclick: () => { draft.fs_roots.splice(i, 1); render(); } }, "Remover"))));
    const folders = section("Pastas liberadas para arquivos e comandos", rootsList,
      h("div", { style: { display: "flex", gap: "8px" } }, rootInput,
        h("button", { class: "btn", type: "button", onclick: () => { const v = rootInput.value.trim(); if (v) { draft.fs_roots.push(v); render(); } } }, "Adicionar")),
      h("p", { class: "hint" }, `Fora dessas pastas a Sexta-Feira não lê nem altera nada. Arquivos de credenciais (.env, .ssh, chaves) e a pasta de dados (${data.paths.data}) são sempre protegidos.`));

    const saveBar = h("div", { class: "save-bar" },
      h("button", { class: "btn ghost", type: "button", onclick: () => { draft = structuredClone(data.runtime); render(); } }, "Descartar"),
      h("button", { class: "btn primary", type: "button", onclick: save }, "Salvar configurações"));

    clear(body).append(profile, autonomy, permissions, routing, budget, folders, saveBar);
  }

  async function save() {
    try {
      await api("/api/settings", { method: "PUT", body: draft });
      toast("Configurações salvas.", "good");
      await load();
      refreshStatus().catch(() => {});
    } catch (err) { toast(err.message, "bad", 7000); }
  }

  load();
  return null;
}

const RISK_ORDER = ["safe", "read", "write", "exec", "critical"];
function riskOrder(a, b) { return RISK_ORDER.indexOf(a) - RISK_ORDER.indexOf(b); }
