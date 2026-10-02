// Configurações: perfil, voz, informações, autonomia, permissões, modelos, orçamento, internet e pastas.

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

    // --- Informações (notícias, mercado, clima, resumos)
    const listInput = (key, placeholder, transform = (v) => v) => {
      const input = h("input", { type: "text", value: rt[key].join(", "), placeholder });
      input.addEventListener("input", () => {
        draft[key] = input.value.split(",").map((v) => transform(v.trim())).filter(Boolean);
      });
      return input;
    };
    const categories = data.news_categories || {};
    const topicChecks = h("div", { class: "checks" }, Object.entries(categories).map(([key, label]) => {
      const box = h("input", { type: "checkbox", checked: rt.news_topics.includes(key) });
      box.addEventListener("change", () => {
        const set = new Set(draft.news_topics);
        if (box.checked) set.add(key); else set.delete(key);
        draft.news_topics = Object.keys(categories).filter((c) => set.has(c));
      });
      return h("label", { class: "check" }, box, label);
    }));
    const intel = section("Informações: notícias, mercado, clima e resumos",
      h("div", { class: "form-grid" },
        h("label", { class: "switch" }, bind("intel_enabled", h("input", { type: "checkbox", checked: rt.intel_enabled })), "Atualizar e verificar alertas automaticamente"),
        h("label", { class: "switch" }, bind("briefing_enabled", h("input", { type: "checkbox", checked: rt.briefing_enabled })), "Gerar resumos automáticos")),
      h("div", { class: "form-grid" },
        h("label", { class: "field" }, "Sua cidade (clima)", bind("city", h("input", { type: "text", value: rt.city, maxlength: 80, placeholder: "Ex.: Campinas" }))),
        h("label", { class: "field" }, "Horários dos resumos", listInput("briefing_times", "08:00, 18:00"))),
      h("label", { class: "field" }, "Ativos acompanhados", listInput("watchlist", "IBOV, USD, BTC, PETR4", (v) => v.toUpperCase())),
      h("div", { class: "field" }, "Temas de notícias", topicChecks),
      h("p", { class: "hint" },
        "Ativos: ações da B3 (PETR4), dos EUA (AAPL), índices (IBOV, SP500, NASDAQ), moedas (USD, EUR) e cripto (BTC, ETH). ",
        "Fontes públicas e gratuitas: Open-Meteo, Banco Central (SGS), AwesomeAPI, CoinGecko, Yahoo Finance, Google Notícias e feeds de G1, Agência Brasil, BBC e outros. ",
        "Os resumos usam a camada Equilibrado (custo baixo); sem IA, sai um resumo simples a partir dos dados."));

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

    clear(body).append(profile, voicePanel, intel, autonomy, permissions, routing, budget, folders, saveBar);
  }

  async function save() {
    // Envia só o que mudou (a seção de voz salva na hora e não pode ser sobrescrita).
    const changes = {};
    for (const [key, value] of Object.entries(draft)) {
      if (JSON.stringify(value) !== JSON.stringify(data.runtime[key])) changes[key] = value;
    }
    if (!Object.keys(changes).length) return toast("Nada para salvar.", "info");
    try {
      await api("/api/settings", { method: "PUT", body: changes });
      toast("Configurações salvas.", "good");
      await load();
      refreshStatus().catch(() => {});
    } catch (err) { toast(err.message, "bad", 7000); }
  }

  // --- Voz e ativação ------------------------------------------------------------
  const ENGINES = [
    ["local", "Local no PC", "Microfone direto, reconhecimento offline e voz do Windows. Funciona sem janela aberta."],
    ["navegador", "Navegador", "Microfone e vozes do Chrome/Edge (precisa da janela aberta)."],
    ["desligado", "Desligado", "Sem voz."],
  ];
  const WHISPER = [
    ["base", "Base — rápido (~145 MB)"],
    ["small", "Small — recomendado (~470 MB)"],
    ["medium", "Medium — mais preciso, mais lento (~1,5 GB)"],
    ["large-v3-turbo", "Large v3 Turbo — máxima precisão, PC forte (~1,6 GB)"],
  ];
  const voicePanel = h("section", { class: "panel" });
  const meterFill = h("span", { class: "fill" });
  const meterMark = h("span", { class: "mark" });
  const meter = h("div", { class: "meter", title: "Nível do microfone (a linha laranja é o limite para uma palma)" }, meterFill, meterMark);
  const clapInfo = h("span", { class: "hint" }, "Bata duas palmas para testar.");
  const autostartSwitch = h("input", { type: "checkbox", disabled: true });
  const autostartWindow = h("input", { type: "checkbox" });
  const autostartHint = h("span", { class: "hint" }, "verificando…");
  let claps = 0;
  let serverVoice = null;
  let devices = null;
  let sapiVoices = null;
  let downloadText = "";

  async function refreshVoiceInfo() {
    try { serverVoice = await api("/api/voice/status"); } catch { serverVoice = null; }
    renderVoicePanel();
  }
  async function loadDevices() {
    try { devices = await api("/api/voice/devices"); } catch (err) { devices = { error: err.message }; }
    renderVoicePanel();
  }
  async function loadSapiVoices() {
    try { sapiVoices = await api("/api/voice/voices"); } catch { sapiVoices = []; }
    renderVoicePanel();
  }
  async function setServer(patch) {
    try {
      data.runtime = await api("/api/settings", { method: "PUT", body: patch });
      Object.assign(draft, patch);
      renderVoicePanel();
      setTimeout(refreshVoiceInfo, 700);
      refreshStatus().catch(() => {});
    } catch (err) { toast(err.message, "bad", 7000); }
  }
  const post = (path, ok) => api(path, { method: "POST" }).then(() => ok && toast(ok, "good")).catch((err) => toast(err.message, "bad"));

  function serverToggle(rt, key, label) {
    const input = h("input", { type: "checkbox", checked: rt[key] });
    input.addEventListener("change", () => setServer({ [key]: input.checked }));
    return h("label", { class: "switch" }, input, label);
  }
  function serverRange(rt, key, min, max, step, label, fmtValue) {
    const out = h("span", { class: "hint" }, fmtValue(rt[key]));
    const input = h("input", { type: "range", min, max, step, value: rt[key] });
    input.addEventListener("input", () => { out.textContent = fmtValue(Number(input.value)); });
    input.addEventListener("change", () => setServer({ [key]: Number(input.value) }));
    return h("label", { class: "field" }, h("span", {}, label, " ", out), input);
  }
  function serverSelect(rt, key, options, label) {
    const select = h("select", {}, options.map(([value, text]) => h("option", { value, selected: rt[key] === value }, text)));
    select.addEventListener("change", () => setServer({ [key]: select.value }));
    return h("label", { class: "field" }, label, select);
  }

  function renderLocal(rt) {
    const sv = serverVoice || {};
    const models = sv.models || {};
    const deviceOptions = [["", "Padrão do Windows"]];
    if (Array.isArray(devices)) devices.forEach((d) => deviceOptions.push([d.name, `${d.name}${d.default ? " (padrão)" : ""}`]));
    if (rt.voice_input_device && !deviceOptions.some(([v]) => v === rt.voice_input_device)) deviceOptions.push([rt.voice_input_device, rt.voice_input_device]);
    const voiceOptions = [["", "Automática (português, se instalada)"], ...(sapiVoices || []).map((v) => [v, v])];
    if (rt.voice_tts_voice && !voiceOptions.some(([v]) => v === rt.voice_tts_voice)) voiceOptions.push([rt.voice_tts_voice, rt.voice_tts_voice]);
    return [
      h("div", { class: "voice-status" },
        h("span", { class: `tag ${sv.state === "error" ? "red" : sv.state === "idle" ? "green" : "cyan"}` }, `estado: ${sv.state || "…"}`),
        h("span", { class: `tag ${models.vosk ? "green" : "amber"}` }, models.vosk ? "ativação: modelo ok" : "ativação: baixar modelo"),
        h("span", { class: `tag ${models.whisper ? "green" : "amber"}` }, models.whisper ? `transcrição: ${models.whisper_size} ok` : `transcrição: baixar ${models.whisper_size || ""}`),
        sv.speaker ? h("span", { class: "tag" }, `fala: ${sv.speaker}`) : null,
        sv.device ? h("span", { class: "tag" }, `microfone: ${sv.device}`) : null),
      sv.error ? h("div", { class: "alert-line" }, sv.error) : sv.detail ? h("p", { class: "hint" }, sv.detail) : null,
      downloadText ? h("p", { class: "hint" }, downloadText) : null,
      h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap" } },
        h("button", { class: "btn", type: "button", onclick: () => post("/api/voice/models/download", "Download dos modelos iniciado.") }, "Baixar modelos"),
        h("button", { class: "btn", type: "button", onclick: () => post("/api/voice/restart", "Reiniciando a voz…") }, "Reiniciar voz"),
        h("button", { class: "btn", type: "button", onclick: () => post("/api/voice/activate") }, "Ativar agora"),
        h("button", { class: "btn", type: "button", onclick: testVoice }, "Testar fala")),
      h("div", { class: "levels" }, [["ambos", "Ambos", "Fala as respostas dos pedidos feitos por voz."], ["voz", "Voz", "Fala todas as respostas (inclusive digitadas)."]].map(([value, label, desc]) => h("button", {
        type: "button", class: `level ${rt.voice_mode === value ? "on" : ""}`, onclick: () => setServer({ voice_mode: value }),
      }, h("strong", {}, label), h("span", {}, desc)))),
      h("div", { class: "form-grid" },
        serverToggle(rt, "voice_wake", "Ativar com “Olá, Sexta-Feira”"),
        serverToggle(rt, "voice_name_only", "Aceitar também “Sexta-Feira, …”"),
        serverToggle(rt, "voice_claps", "Ativar com duas palmas"),
        serverToggle(rt, "voice_speak_alerts", "Falar alertas e resumos")),
      h("div", { class: "form-grid" },
        h("div", { class: "field" }, serverRange(rt, "voice_clap_sensitivity", 0, 1, 0.05, "Sensibilidade das palmas", (v) => `${Math.round(v * 100)}%`), meter, clapInfo),
        serverSelect(rt, "voice_input_device", deviceOptions, Array.isArray(devices) ? "Microfone" : `Microfone ${devices?.error ? "(indisponível)" : ""}`),
        serverSelect(rt, "voice_tts_voice", voiceOptions, "Voz do Windows"),
        serverRange(rt, "voice_tts_rate", -10, 10, 1, "Velocidade da fala", (v) => (v > 0 ? `+${v}` : `${v}`)),
        serverSelect(rt, "voice_whisper_model", WHISPER, "Modelo de transcrição")),
      h("p", { class: "hint" },
        "Tudo roda no seu computador: o áudio não sai do PC — só o texto do pedido vai para a IA. ",
        "Para a voz em português, instale no Windows: Configurações → Hora e idioma → Fala → Português (Brasil). ",
        "Confirmações por voz valem apenas para ações não críticas."),
    ];
  }

  function renderBrowser() {
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
    return [
      h("div", { class: "voice-status" },
        h("span", { class: `tag ${voice.supported.recognition ? "green" : "red"}` }, voice.supported.recognition ? "reconhecimento de fala: ok" : "reconhecimento: use Chrome/Edge"),
        h("span", { class: `tag ${voice.supported.claps ? "green" : "red"}` }, voice.supported.claps ? "palmas: ok" : "palmas: indisponível"),
        h("span", { class: "tag cyan" }, `estado: ${voice.state}`)),
      h("div", { class: "levels" }, VOICE_MODES.map(([value, label, desc]) => h("button", {
        type: "button", class: `level ${vs.mode === value ? "on" : ""}`, onclick: () => set({ mode: value }),
      }, h("strong", {}, label), h("span", {}, desc)))),
      h("div", { class: "form-grid" },
        toggle("wake", "Ativar com “Olá, Sexta-Feira”"),
        toggle("nameOnly", "Aceitar também “Sexta-Feira, …”"),
        toggle("claps", "Ativar com duas palmas")),
      h("div", { class: "form-grid" },
        h("div", { class: "field" }, range("clapSensitivity", 0, 1, 0.05, "Sensibilidade das palmas", (v) => `${Math.round(v * 100)}%`), meter, clapInfo),
        h("label", { class: "field" }, "Voz do navegador", voiceSelect),
        range("rate", 0.7, 1.5, 0.05, "Velocidade da fala", (v) => `${v.toFixed(2)}×`),
        range("pitch", 0.5, 1.5, 0.05, "Tom da voz", (v) => v.toFixed(2))),
      h("button", { class: "btn", type: "button", onclick: testVoice }, "Testar voz"),
      h("p", { class: "hint" },
        "O reconhecimento de fala do navegador envia o áudio ao Google (Chrome) ou à Microsoft (Edge) enquanto escuta. ",
        "Prefira o motor “Local no PC” para privacidade total."),
    ];
  }

  function renderVoicePanel() {
    const rt = data?.runtime;
    const head = h("div", { class: "panel-head" }, "Voz e ativação");
    if (!rt) return fill(voicePanel, head, h("div", { class: "panel-body" }, h("p", { class: "hint" }, "Carregando…")));
    const engine = rt.voice_engine;
    return fill(voicePanel, head, h("div", { class: "panel-body" },
      h("div", { class: "levels" }, ENGINES.map(([value, label, desc]) => h("button", {
        type: "button", class: `level ${engine === value ? "on" : ""}`, onclick: () => setServer({ voice_engine: value }),
      }, h("strong", {}, label), h("span", {}, desc)))),
      engine === "local" ? renderLocal(rt) : engine === "navegador" ? renderBrowser() : h("p", { class: "hint" }, "A voz está desligada."),
      h("div", { style: { display: "flex", gap: "14px", flexWrap: "wrap", alignItems: "center" } },
        h("label", { class: "switch" }, autostartSwitch, "Iniciar com o Windows"),
        h("label", { class: "switch" }, autostartWindow, "Abrir a interface ao ligar"),
        autostartHint)));
  }

  async function loadAutostart() {
    try {
      const status = await api("/api/system/autostart");
      autostartSwitch.checked = Boolean(status.enabled);
      autostartSwitch.disabled = !status.supported;
      autostartWindow.checked = Boolean(status.window);
      autostartWindow.disabled = !status.supported;
      autostartHint.textContent = !status.supported ? "disponível só no Windows"
        : status.enabled && !status.up_to_date ? "desatualizado — desligue e ligue de novo" : "";
    } catch (err) { autostartHint.textContent = err.message; }
  }
  async function changeAutostart() {
    try {
      await api("/api/system/autostart", { method: "PUT", body: { enabled: autostartSwitch.checked, window: autostartWindow.checked } });
      toast(autostartSwitch.checked ? "A Sexta-Feira vai iniciar com o Windows." : "Início automático desligado.", "good");
    } catch (err) { toast(err.message, "bad"); }
    loadAutostart();
  }
  autostartSwitch.addEventListener("change", changeAutostart);
  autostartWindow.addEventListener("change", () => { if (autostartSwitch.checked) changeAutostart(); });

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
  const offVoices = on("voice-voices", () => { if (data?.runtime?.voice_engine === "navegador") renderVoicePanel(); });
  let stateTimer = null;
  const offState = on("voice-state", () => { clearTimeout(stateTimer); stateTimer = setTimeout(refreshVoiceInfo, 300); });
  const offLive = on("live", (ev) => {
    if (ev.type !== "voice_download") return;
    if (ev.error) downloadText = `Falha no download: ${ev.error}`;
    else if (ev.done) downloadText = "Modelos prontos ✔";
    else downloadText = `Baixando ${ev.model}: ${Math.round((ev.progress || 0) * 100)}%`;
    renderVoicePanel();
  });

  renderVoicePanel();
  loadAutostart();
  load().then(() => { refreshVoiceInfo(); loadDevices(); loadSapiVoices(); });
  return () => { offLevel(); offClap(); offDouble(); offVoices(); offState(); offLive(); clearTimeout(stateTimer); };
}

const RISK_ORDER = ["safe", "read", "write", "exec", "critical"];
function riskOrder(a, b) { return RISK_ORDER.indexOf(a) - RISK_ORDER.indexOf(b); }
