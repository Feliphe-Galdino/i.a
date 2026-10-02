// Tela de chat: conversas, streaming da resposta, raciocínio, ferramentas e aprovações.

import { api, live } from "../api.js";
import { renderMarkdown } from "../markdown.js";
import { emit, on, setCurrentConversation, state } from "../state.js";
import { add, clear, debounce, fill, fmt, h, riskTag, STATUS_LABEL, toast } from "../ui.js";

const MODES = [
  ["auto", "Auto"],
  ["rapido", "Rápido"],
  ["equilibrado", "Equilibrado"],
  ["profundo", "Profundo"],
];

const SUGGESTIONS = [
  ["Programação", "Crie um script Python que organize minha pasta de trabalho por tipo de arquivo"],
  ["Memória", "Lembre que eu prefiro explicações com exemplos práticos"],
  ["Sistema", "Como está o desempenho do meu computador agora?"],
  ["Pesquisa", "Quais são as principais notícias de tecnologia de hoje?"],
  ["Estudos", "Monte um plano de estudos de 4 semanas para eu aprender FastAPI"],
  ["Automação", "Liste os arquivos da minha pasta de trabalho"],
];

const FINAL_TOOL_STATES = new Set(["done", "error", "blocked", "denied", "rejected"]);

/** Mensagem da assistente (ao vivo ou do histórico). */
class AssistantView {
  constructor({ live: isLive = false } = {}) {
    this.meta = h("div", { class: "msg-meta" }, h("span", { class: "who" }, "SEXTA-FEIRA"));
    this.reasons = h("div", { class: "reasons" });
    this.ctx = h("details", { class: "ctx hidden" });
    this.thinkBody = h("div", { class: "think-body" });
    this.think = h("details", { class: "think hidden" }, h("summary", {}, "Raciocínio"), this.thinkBody);
    this.body = h("div", { class: "body" });
    this.indicator = isLive ? h("span", { class: "live-indicator" }, "processando") : null;
    this.cost = h("span", {});
    this.foot = h("div", { class: "msg-foot" }, this.indicator, this.cost);
    this.el = h("div", { class: "msg assistant" },
      h("div", { class: "frame panel" }, this.meta, this.reasons, this.ctx, this.think, this.body, this.foot));
    this.text = null; // segmento de texto atual { el, buffer }
    this.tools = new Map();
    this.renderPending = false;
  }

  setRoute(route) {
    if (!route) return;
    add(this.meta,
      h("span", { class: "tag cyan" }, route.model_label || route.model),
      h("span", { class: "tag" }, route.tier_label || route.tier),
      route.effort ? h("span", { class: "tag violet" }, `esforço ${route.effort}`) : null,
      h("span", { class: "tag" }, route.agent_name),
    );
    if (route.reasons?.length) this.reasons.textContent = route.reasons.join(" · ");
  }

  setContext(memories, webSearch) {
    if (!memories?.length) return;
    clear(this.ctx).append(
      h("summary", {}, `${memories.length} memória(s) usada(s)${webSearch ? " · busca na web disponível" : ""}`),
      h("ul", { class: "ctx-body" }, memories.map((m) => h("li", {}, `[${m.category}] ${m.content}`))),
    );
    this.ctx.classList.remove("hidden");
  }

  addThinking(text) {
    this.think.classList.remove("hidden");
    this.thinkBody.textContent += text;
    this.setIndicator("raciocinando");
  }

  addText(text) {
    if (!this.text) {
      this.text = { el: h("div", { class: "md" }), buffer: "" };
      this.body.append(this.text.el);
    }
    this.text.buffer += text;
    this.setIndicator("escrevendo");
    this.scheduleRender();
  }

  setText(text) {
    if (!text) return;
    this.text = null;
    this.addText(text);
    this.flush();
  }

  resetText() {
    if (this.text) { this.text.buffer = ""; this.text.el.textContent = ""; }
  }

  scheduleRender() {
    if (this.renderPending) return;
    this.renderPending = true;
    requestAnimationFrame(() => this.flush());
  }

  flush() {
    this.renderPending = false;
    if (this.text) this.text.el.innerHTML = renderMarkdown(this.text.buffer); // markdown.js escapa tudo
  }

  addTool({ id, name, server = false, input, result, status = "pending", is_error = false, summary, risk }) {
    this.flush();
    this.text = null; // o próximo texto vira um novo segmento, depois da ferramenta
    const card = {
      status: h("span", { class: "tool-status" }),
      summary: h("span", { class: "summary" }, summary || (server ? "busca na web" : "")),
      risk: h("span", {}),
      input: h("pre", { class: "hidden" }),
      result: h("pre", { class: "hidden" }),
    };
    card.el = h("div", { class: "tool-card" },
      h("div", { class: "tool-head", onclick: () => card.el.classList.toggle("open") },
        h("span", { class: "name" }, server ? `🌐 ${name}` : name), card.summary, card.risk, card.status),
      h("div", { class: "tool-body" }, card.input, card.result));
    this.tools.set(id, card);
    this.body.append(card.el);
    this.updateTool(id, { status, input, result, is_error, summary, risk });
    return card;
  }

  updateTool(id, { status, input, result, is_error, summary, risk }) {
    const card = this.tools.get(id);
    if (!card) return;
    if (status) {
      card.el.className = `tool-card ${status === "awaiting_approval" ? "awaiting" : status} ${card.el.classList.contains("open") ? "open" : ""}`;
      card.status.textContent = STATUS_LABEL[status] || status;
      this.setIndicator(status === "awaiting_approval" ? "aguardando sua confirmação" : FINAL_TOOL_STATES.has(status) ? "processando" : "executando ferramenta");
    }
    if (summary) card.summary.textContent = summary;
    if (risk) clear(card.risk).append(riskTag(risk));
    if (input !== undefined && input !== null) { card.input.textContent = `entrada:\n${fmt.json(input)}`; card.input.classList.remove("hidden"); }
    if (result !== undefined && result !== null) {
      card.result.textContent = `resultado:\n${result}`;
      card.result.classList.remove("hidden");
      if (is_error && !status) card.el.classList.add("error");
    }
  }

  alert(message, kind = "") {
    this.flush();
    this.text = null;
    this.body.append(h("div", { class: `alert-line ${kind}` }, message));
  }

  setIndicator(label) { if (this.indicator) this.indicator.textContent = label; }

  finish(done) {
    this.flush();
    if (this.indicator) { this.indicator.remove(); this.indicator = null; }
    if (done) {
      const parts = [];
      if (done.cost_usd) parts.push(fmt.usd(done.cost_usd));
      if (done.usage?.output_tokens) parts.push(`${fmt.num(done.usage.input_tokens + (done.usage.cache_read_tokens || 0))} → ${fmt.num(done.usage.output_tokens)} tokens`);
      if (done.status && done.status !== "done") parts.push(`tarefa ${done.status}`);
      this.cost.textContent = parts.join(" · ");
    }
  }
}

export function mount(root) {
  let convId = state.currentConversation;
  let mode = "auto";
  const views = new Map();       // task_id -> AssistantView
  const buffered = new Map();    // eventos que chegaram antes do task_accepted
  const myRefs = new Set();
  const voiceRefs = new Set();
  let conversations = [];

  // ---------- Estrutura ----------
  const search = h("input", { type: "search", placeholder: "Buscar conversas…", "aria-label": "Buscar conversas" });
  const list = h("div", { class: "convs-list" });
  const newBtn = h("button", { class: "btn small", title: "Nova conversa", onclick: () => openConversation(null) }, "+ Nova");
  const convs = h("aside", { class: "convs" }, h("div", { class: "convs-head" }, search, newBtn), list);

  const title = h("strong", { style: { flex: "1", minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-ui)", letterSpacing: "0.05em" } });
  const menuBtn = h("button", { class: "btn ghost small", title: "Conversas", onclick: () => chat.classList.toggle("show-convs") }, "☰");
  const renameBtn = h("button", { class: "btn ghost small", title: "Renomear", onclick: renameConversation }, "Renomear");
  const deleteBtn = h("button", { class: "btn ghost small", title: "Excluir conversa", onclick: deleteConversation }, "Excluir");
  const head = h("div", { class: "stage-head", style: { display: "flex" } }, menuBtn, title, renameBtn, deleteBtn);

  const inner = h("div", { class: "stream-inner" });
  const stream = h("div", { class: "stream", "aria-live": "polite" }, inner);

  const textarea = h("textarea", { rows: 1, placeholder: "Fale com a Sexta-Feira…  (Enter envia · Shift+Enter quebra linha)", "aria-label": "Mensagem" });
  const modeSeg = h("div", { class: "seg", role: "group", "aria-label": "Modo do modelo" },
    MODES.map(([value, label]) => h("button", { type: "button", "data-mode": value, class: value === mode ? "on" : "", title: modeHint(value), onclick: () => setMode(value) }, label)));
  const stopBtn = h("button", { class: "btn danger small hidden", type: "button", onclick: stopCurrent }, "■ Parar");
  const sendBtn = h("button", { class: "btn primary", type: "submit" }, "Enviar");
  const form = h("form", { class: "composer panel" }, textarea,
    h("div", { class: "composer-row" }, modeSeg, h("span", { class: "spacer" }), stopBtn, sendBtn));
  const chat = h("div", { class: "chat" }, convs, h("section", { class: "stage" }, head, stream, h("div", { class: "composer-wrap" }, form)));
  root.append(chat);

  // ---------- Comportamento ----------
  form.addEventListener("submit", (e) => { e.preventDefault(); send(); });
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  textarea.addEventListener("input", autoGrow);
  search.addEventListener("input", debounce(renderList, 150));
  stream.addEventListener("click", (e) => {
    const btn = e.target.closest(".copy");
    if (!btn) return;
    const code = btn.parentElement.querySelector("code");
    navigator.clipboard?.writeText(code.textContent).then(() => { btn.textContent = "copiado"; setTimeout(() => (btn.textContent = "copiar"), 1500); });
  });

  function modeHint(value) {
    return {
      auto: "O MEGABRAIN escolhe o modelo ideal para cada pedido",
      rapido: "Claude Haiku 4.5 — respostas rápidas e econômicas",
      equilibrado: "Claude Sonnet 5.5 — bom equilíbrio entre qualidade e custo",
      profundo: "Claude Opus 5.5 — máxima qualidade para tarefas complexas",
    }[value];
  }

  function setMode(value) {
    mode = value;
    modeSeg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.mode === value));
  }

  function autoGrow() {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(240, textarea.scrollHeight)}px`;
  }

  const nearBottom = () => stream.scrollHeight - stream.scrollTop - stream.clientHeight < 140;
  const scrollDown = (force = false) => { if (force || nearBottom()) stream.scrollTop = stream.scrollHeight; };

  function updateStopButton() {
    const busy = [...state.running.values()].some((t) => t.conversation_id === convId && convId);
    stopBtn.classList.toggle("hidden", !busy && ![...views.keys()].some((id) => state.running.has(id)));
  }

  function stopCurrent() {
    for (const [taskId, info] of state.running) {
      if (info.conversation_id === convId || views.has(taskId)) live.send({ type: "cancel", task_id: taskId });
    }
  }

  // ---------- Conversas ----------
  async function loadConversations() {
    try { conversations = await api("/api/conversations?limit=200"); } catch (err) { toast(err.message, "bad"); }
    renderList();
  }

  function renderList() {
    const q = search.value.trim().toLowerCase();
    const items = conversations.filter((c) => !q || c.title.toLowerCase().includes(q));
    const busy = new Set([...state.running.values()].map((t) => t.conversation_id));
    fill(list,
      items.length ? items.map((c) => h("button", {
        class: `conv-item ${c.id === convId ? "active" : ""}`, title: c.title,
        onclick: () => { openConversation(c.id); chat.classList.remove("show-convs"); },
      }, busy.has(c.id) ? h("span", { class: "busy" }) : null, h("span", { class: "t" }, c.title), h("span", { class: "m" }, fmt.ago(c.updated_at))))
        : h("p", { class: "empty" }, q ? "Nenhuma conversa encontrada." : "Nenhuma conversa ainda."),
    );
    const current = conversations.find((c) => c.id === convId);
    title.textContent = current ? current.title : "Nova conversa";
    renameBtn.disabled = deleteBtn.disabled = !current;
  }
  const refreshList = debounce(loadConversations, 300);

  async function openConversation(id) {
    convId = id;
    setCurrentConversation(id);
    views.clear();
    clear(inner);
    renderList();
    updateStopButton();
    if (!id) return renderWelcome();
    try {
      const data = await api(`/api/conversations/${id}`);
      if (convId !== id) return;
      renderHistory(data.messages);
      scrollDown(true);
    } catch (err) {
      if (err.status === 404) { setCurrentConversation(null); convId = null; renderWelcome(); }
      else toast(err.message, "bad");
    }
  }

  function renderWelcome() {
    const name = state.settings?.runtime?.user_name;
    clear(inner).append(h("div", { class: "welcome" },
      h("div", { class: "core core-lg idle" }, h("i"), h("i"), h("i"), h("b")),
      h("h2", {}, "SEXTA-FEIRA ONLINE"),
      h("p", {}, `${name ? `Olá, ${name}. ` : "Olá! "}Sou sua assistente pessoal. Posso programar, pesquisar, organizar, automatizar tarefas no seu computador e aprender com você.`),
      h("div", { class: "suggestions" }, SUGGESTIONS.map(([label, text]) => h("button", { class: "suggestion", type: "button", onclick: () => { textarea.value = text; send(); } }, h("small", {}, label), text))),
    ));
  }

  function renderHistory(messages) {
    let current = null;
    let currentTask = null;
    for (const m of messages) {
      if (m.role === "user") {
        current = null;
        inner.append(userBubble(m.text));
        continue;
      }
      if (!current || m.task_id !== currentTask) {
        current = new AssistantView();
        currentTask = m.task_id;
        current.meta.append(h("span", { class: "tag cyan" }, m.model || ""), h("span", { class: "tag" }, fmt.time(m.created_at)));
        inner.append(current.el);
      }
      if (m.thinking) current.addThinking(m.thinking);
      if (m.text) current.setText(m.text);
      for (const t of m.tools) {
        current.addTool({ ...t, status: t.server ? "done" : t.is_error || t.result === null ? "error" : "done" });
      }
      current.finish();
    }
  }

  function userBubble(text, viaVoice = false) {
    return h("div", { class: "msg user" }, h("div", { class: "bubble" }, viaVoice ? "🎙 " : null, text));
  }

  async function renameConversation() {
    const current = conversations.find((c) => c.id === convId);
    if (!current) return;
    const value = prompt("Novo título da conversa:", current.title);
    if (!value?.trim()) return;
    try { await api(`/api/conversations/${convId}`, { method: "PATCH", body: { title: value.trim() } }); loadConversations(); }
    catch (err) { toast(err.message, "bad"); }
  }

  async function deleteConversation() {
    if (!convId || !confirm("Excluir esta conversa? As memórias salvas continuam.")) return;
    try { await api(`/api/conversations/${convId}`, { method: "DELETE" }); openConversation(null); loadConversations(); }
    catch (err) { toast(err.message, "bad"); }
  }

  // ---------- Envio e eventos ao vivo ----------
  function send(spoken = null) {
    const viaVoice = typeof spoken === "string";
    const text = (viaVoice ? spoken : textarea.value).trim();
    if (!text) return;
    if (!state.connected) toast("Sem conexão — a mensagem será enviada ao reconectar.", "warn");
    if (inner.querySelector(".welcome")) clear(inner);
    inner.append(userBubble(text, viaVoice));
    scrollDown(true);
    const ref = Math.random().toString(36).slice(2);
    myRefs.add(ref);
    if (viaVoice) voiceRefs.add(ref);
    live.send({ type: "chat", text, conversation_id: convId, mode, client_ref: ref, channel: viaVoice ? "voz" : "texto" });
    if (!viaVoice) {
      textarea.value = "";
      autoGrow();
    }
  }

  function consumeVoiceCommand() {
    const command = state.pendingVoiceCommand;
    if (!command) return;
    state.pendingVoiceCommand = null;
    send(command);
  }

  function attachView(taskId) {
    const view = new AssistantView({ live: true });
    views.set(taskId, view);
    inner.append(view.el);
    for (const ev of buffered.get(taskId) || []) apply(view, ev);
    buffered.delete(taskId);
    scrollDown(true);
    updateStopButton();
    return view;
  }

  function apply(view, ev) {
    switch (ev.type) {
      case "task_started": view.setRoute(ev.route); break;
      case "context": view.setContext(ev.memories, ev.web_search); break;
      case "thinking_delta": view.addThinking(ev.text); break;
      case "text_delta": view.addText(ev.text); break;
      case "stream_reset": view.resetText(); break;
      case "tool_started":
        view.addTool({ id: ev.tool_use_id, name: ev.tool, server: ev.server, status: ev.server ? "running" : "pending" });
        break;
      case "tool_status":
        if (!view.tools.has(ev.tool_use_id)) view.addTool({ id: ev.tool_use_id, name: ev.tool });
        view.updateTool(ev.tool_use_id, ev);
        break;
      case "assistant_message":
        for (const [, card] of view.tools) {
          if (card.el.classList.contains("running") && card.el.querySelector(".name").textContent.startsWith("🌐")) {
            card.el.className = "tool-card done"; card.status.textContent = STATUS_LABEL.done;
          }
        }
        break;
      case "refusal": view.alert(ev.message, "warn"); break;
      case "error": view.alert(ev.message); break;
      case "task_cancelled": view.alert("Tarefa interrompida.", "warn"); break;
      case "task_done":
        view.finish(ev);
        updateStopButton();
        break;
      default: break;
    }
  }

  const offLive = on("live", (ev) => {
    if (ev.type === "task_accepted" && myRefs.has(ev.client_ref)) {
      myRefs.delete(ev.client_ref);
      if (!convId || convId !== ev.conversation_id) {
        convId = ev.conversation_id;
        setCurrentConversation(convId);
        refreshList();
      }
      if (!views.has(ev.task_id)) attachView(ev.task_id);
      return;
    }
    if (ev.type === "error" && !ev.task_id && myRefs.has(ev.client_ref)) {
      myRefs.delete(ev.client_ref);
      if (voiceRefs.delete(ev.client_ref)) emit("voice-failed", ev.message);
      toast(ev.message, "bad");
      return;
    }
    if (ev.type === "conversation_created" || ev.type === "task_done") refreshList();
    if (ev.type === "task_started" || ev.type === "task_done") { renderList(); updateStopButton(); }
    if (!ev.task_id) return;

    let view = views.get(ev.task_id);
    if (!view && ev.type === "task_started" && ev.conversation_id === convId && myRefs.size === 0) {
      view = attachView(ev.task_id); // tarefa iniciada em outra aba/cliente
    }
    if (view) {
      apply(view, ev);
      scrollDown();
    } else {
      const queue = buffered.get(ev.task_id) || [];
      if (queue.length < 2000) queue.push(ev);
      buffered.set(ev.task_id, queue);
      setTimeout(() => buffered.delete(ev.task_id), 60000);
    }
  });

  const offVoice = on("voice-command", consumeVoiceCommand);
  const offVoiceState = on("voice-state", (vs) => {
    const core = inner.querySelector(".welcome .core");
    if (core) core.className = `core core-lg ${vs === "listening" || vs === "speaking" ? vs : vs === "thinking" ? "thinking" : "idle"}`;
  });

  loadConversations();
  openConversation(convId).then(consumeVoiceCommand);
  setTimeout(() => textarea.focus(), 50);

  return () => {
    offLive();
    offVoice();
    offVoiceState();
  };
}
