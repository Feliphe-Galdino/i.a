// Configurações: perfil, autonomia, permissões, modelos, orçamento, internet e pastas.

import { api } from "../api.js";
import { refreshStatus } from "../app.js";
import { on, state } from "../state.js";
import { clear, fill, h, riskTag, toast } from "../ui.js";
import { listVoices, saveVoiceSettings, testVoice, voice } from "../voice/voice.js";

const VOICE_MODES = [
  ["texto", "Texto", "Sem microfone e sem fala."],
  ["ambos", "Ambos", "Ativa por voz/palmas; fala só as respostas a pedidos falados."],
  ["voz", "Voz", "Ativa por voz/palmas e fala todas as respostas."],
];

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

    clear(body).append(profile, voicePanel, autonomy, permissions, routing, budget, folders, saveBar);
  }

  async function save() {
    try {
      await api("/api/settings", { method: "PUT", body: draft });
      toast("Configurações salvas.", "good");
      await load();
      refreshStatus().catch(() => {});
    } catch (err) { toast(err.message, "bad", 7000); }
  }

  // --- Voz e ativação (preferências deste navegador; salvas na hora) -----------
  const voicePanel = h("section", { class: "panel" });
  const meterFill = h("span", { class: "fill" });
  const meterMark = h("span", { class: "mark" });
  const meter = h("div", { class: "meter", title: "Nível do microfone (a linha laranja é o limite para uma palma)" }, meterFill, meterMark);
  const clapInfo = h("span", { class: "hint" }, "Bata duas palmas para testar.");
  const autostartSwitch = h("input", { type: "checkbox", disabled: true });
  const autostartHint = h("span", { class: "hint" }, "verificando…");
  let claps = 0;

  function renderVoicePanel() {
    const vs = voice.settings;
    const set = (patch) => { saveVoiceSettings(patch); renderVoicePanel(); };
    const toggle = (key, label) => {
      const input = h("input", { type: "checkbox", checked: vs[key] });
      input.addEventListener("change", () => set({ [key]: input.checked }));
      return h("label", { class: "switch" }, input, label);
    };
    const range = (key, min, max, step, label, fmtValue) => {
      const out = h("span", { class: "hint" }, fmtValue(vs[key]));
      const input = h("input", { type: "range", min, max, step, value: vs[key] });
      input.addEventListener("input", () => { out.textContent = fmtValue(Number(input.value)); saveVoiceSettings({ [key]: Number(input.value) }); });
      return h("label", { class: "field" }, h("span", {}, label, " ", out), input);
    };
    const voices = listVoices();
    const voiceSelect = h("select", {},
      h("option", { value: "" }, "Automática (melhor voz em português)"),
      voices.map((v) => h("option", { value: v.voiceURI, selected: v.voiceURI === vs.voiceURI }, `${v.name} (${v.lang})`)));
    voiceSelect.addEventListener("change", () => saveVoiceSettings({ voiceURI: voiceSelect.value }));

    fill(voicePanel,
      h("div", { class: "panel-head" }, "Voz e ativação"),
      h("div", { class: "panel-body" },
        h("div", { class: "voice-status" },
          h("span", { class: `tag ${voice.supported.recognition ? "green" : "red"}` }, voice.supported.recognition ? "reconhecimento de fala: ok" : "reconhecimento de fala: use Chrome/Edge"),
          h("span", { class: `tag ${voice.supported.claps ? "green" : "red"}` }, voice.supported.claps ? "palmas: ok" : "palmas: indisponível"),
          h("span", { class: `tag ${voice.supported.synthesis ? "green" : "red"}` }, voice.supported.synthesis ? `vozes: ${voices.length}` : "fala: indisponível"),
          h("span", { class: "tag cyan" }, `estado: ${voice.state}`),
          voice.error ? h("span", { class: "tag red", title: voice.error }, "erro de microfone") : null),
        h("div", { class: "levels" }, VOICE_MODES.map(([value, label, desc]) => h("button", {
          type: "button", class: `level ${vs.mode === value ? "on" : ""}`, onclick: () => set({ mode: value }),
        }, h("strong", {}, label), h("span", {}, desc)))),
        h("div", { class: "form-grid" },
          toggle("wake", "Ativar com “Olá, Sexta-Feira”"),
          toggle("nameOnly", "Aceitar também “Sexta-Feira, …” (sem saudação)"),
          toggle("claps", "Ativar com duas palmas")),
        h("div", { class: "form-grid" },
          h("div", { class: "field" }, range("clapSensitivity", 0, 1, 0.05, "Sensibilidade das palmas", (v) => `${Math.round(v * 100)}%`), meter, clapInfo),
          h("label", { class: "field" }, "Voz da assistente", voiceSelect),
          range("rate", 0.7, 1.5, 0.05, "Velocidade da fala", (v) => `${v.toFixed(2)}×`),
          range("pitch", 0.5, 1.5, 0.05, "Tom da voz", (v) => v.toFixed(2))),
        h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" } },
          h("button", { class: "btn", type: "button", onclick: testVoice }, "Testar voz"),
          h("label", { class: "switch" }, autostartSwitch, "Iniciar com o Windows (abre a janela de voz ao ligar o PC)"),
          autostartHint),
        h("p", { class: "hint" },
          "Privacidade: as palmas são detectadas no seu computador. Já o reconhecimento de fala do navegador envia o áudio ao serviço do Google (Chrome) ou da Microsoft (Edge) enquanto escuta. ",
          "Para enviar áudio só depois de ativar, desligue “Olá, Sexta-Feira” e use as palmas ou o botão do microfone. ",
          "Confirmações por voz valem apenas para ações não críticas.")));
  }

  async function loadAutostart() {
    try {
      const status = await api("/api/system/autostart");
      autostartSwitch.checked = Boolean(status.enabled);
      autostartSwitch.disabled = !status.supported;
      autostartHint.textContent = !status.supported ? "disponível só no Windows"
        : status.enabled && !status.up_to_date ? "desatualizado — desligue e ligue de novo" : "";
    } catch (err) { autostartHint.textContent = err.message; }
  }
  autostartSwitch.addEventListener("change", async () => {
    try {
      await api("/api/system/autostart", { method: "PUT", body: { enabled: autostartSwitch.checked } });
      toast(autostartSwitch.checked ? "A Sexta-Feira vai iniciar com o Windows." : "Início automático desligado.", "good");
    } catch (err) { toast(err.message, "bad"); }
    loadAutostart();
  });

  const offLevel = on("voice-level", (lvl) => {
    meterFill.style.width = `${Math.min(100, Math.sqrt(lvl.peak) * 100)}%`;
    meterMark.style.left = `${Math.min(100, Math.sqrt(lvl.threshold) * 100)}%`;
  });
  const offClap = on("voice-clap", () => {
    claps++;
    clapInfo.textContent = `Palmas detectadas: ${claps}`;
    meter.classList.add("flash");
    setTimeout(() => meter.classList.remove("flash"), 250);
  });
  const offDouble = on("voice-double-clap", () => { clapInfo.textContent = `Palmas detectadas: ${claps} — ativação! ✔`; });
  const offVoices = on("voice-voices", renderVoicePanel);
  const offState = on("voice-state", renderVoicePanel);

  renderVoicePanel();
  loadAutostart();
  load();
  return () => { offLevel(); offClap(); offDouble(); offVoices(); offState(); };
}

const RISK_ORDER = ["safe", "read", "write", "exec", "critical"];
function riskOrder(a, b) { return RISK_ORDER.indexOf(a) - RISK_ORDER.indexOf(b); }
