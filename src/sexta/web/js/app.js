// Inicialização da interface: acesso, rotas, status em tempo real e eventos globais.

import { api, live, captureTokenFromUrl, getToken, setToken, clearToken, OFFLINE_MESSAGE } from "./api.js";
import * as approvals from "./approvals.js";
import { emit, on, state } from "./state.js";
import { clear, fmt, toast } from "./ui.js";
import * as chat from "./views/chat.js";
import * as dashboard from "./views/dashboard.js";
import * as world from "./views/world.js";
import * as memory from "./views/memory.js";
import * as activity from "./views/activity.js";
import * as settings from "./views/settings.js";
import { initVoice, voice } from "./voice/voice.js";

const VIEWS = { chat, painel: dashboard, mundo: world, memoria: memory, atividade: activity, config: settings };
let unmount = null;
let statusTimer = null;
let voiceStarted = false;

const $ = (id) => document.getElementById(id);

async function boot() {
  captureTokenFromUrl();
  if (!getToken()) return showLogin();
  try {
    await refreshStatus();
  } catch (err) {
    if (err.status === 401) {
      clearToken();
      return showLogin("Token inválido. Use o link exibido no terminal ou rode `sexta token`.");
    }
    toast(`Falha ao conectar: ${err.message}`, "bad");
  }
  try { state.settings = await api("/api/settings"); } catch { /* tenta de novo depois */ }
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");

  let wasConnected = false;
  let lostAt = 0;
  live.onStatus((connected, code) => {
    state.connected = connected;
    if (code === 4401) { clearToken(); location.reload(); }
    if (!connected && wasConnected && !lostAt) {
      lostAt = Date.now();
      setTimeout(() => { if (!state.connected) toast(OFFLINE_MESSAGE, "bad", 15000); }, 4000);
    }
    if (connected && lostAt) {
      // O servidor voltou: recarrega a tela atual e o status.
      lostAt = 0;
      toast("Conexão restabelecida.", "good", 3000);
      refreshStatus().catch(() => {});
      route();
    }
    wasConnected = wasConnected || connected;
    renderChips();
  });
  live.on(handleEvent);
  live.connect();

  window.addEventListener("hashchange", route);
  route();
  if (!voiceStarted) {
    voiceStarted = true;
    initVoice();
    on("voice-state", updateCore);
  }
  $("panic-btn").addEventListener("click", panic);
  clearInterval(statusTimer);
  statusTimer = setInterval(() => refreshStatus().catch(() => {}), 5000);
}

function showLogin(error = "") {
  $("app").classList.add("hidden");
  $("login").classList.remove("hidden");
  $("login-error").textContent = error;
  $("login-form").onsubmit = (e) => {
    e.preventDefault();
    setToken($("login-token").value.trim());
    boot();
  };
}

function route() {
  const name = (location.hash.replace(/^#\/?/, "") || "chat").split("/")[0];
  const view = VIEWS[name] ? name : "chat";
  document.querySelectorAll(".rail a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  if (unmount) unmount();
  const root = clear($("view"));
  unmount = VIEWS[view].mount(root) || null;
  $("view").focus({ preventScroll: true });
}

export async function refreshStatus() {
  state.status = await api("/api/status");
  for (const id of [...state.running.keys()]) {
    if (!state.status.running_tasks.includes(id)) state.running.delete(id);
  }
  renderChips();
  emit("status", state.status);
}

function renderChips() {
  const s = state.status;
  const conn = $("chip-conn");
  conn.className = `chip ${state.connected ? "ok" : "bad"}`;
  conn.querySelector(".label").textContent = state.connected ? "Online" : "Reconectando";
  updateCore();
  if (!s) return;
  $("brand-sub").textContent = s.online ? "MEGABRAIN ATIVO" : "MODO OFFLINE";
  const prov = $("chip-provider");
  prov.textContent = s.online ? "Claude" : "Offline";
  prov.className = `chip hide-sm ${s.online ? "accent" : "warn"}`;
  const auto = $("chip-autonomy");
  auto.textContent = `Autonomia: ${s.autonomy_name}`;
  auto.className = `chip hide-sm ${s.autonomy_level >= 3 ? "warn" : ""}`;
  $("chip-cpu").textContent = `CPU ${Math.round(s.system.cpu_percentual)}%`;
  $("chip-ram").textContent = `RAM ${Math.round(s.system.memoria_percentual)}%`;
  const cost = $("chip-cost");
  const ratio = s.daily_budget_usd ? s.spent_today_usd / s.daily_budget_usd : 0;
  cost.textContent = `${fmt.usd(s.spent_today_usd)} / ${fmt.usd(s.daily_budget_usd)}`;
  cost.className = `chip hide-xs ${ratio >= 1 ? "bad" : ratio >= 0.8 ? "warn" : ""}`;
}

function updateCore() {
  const core = $("mini-core");
  let mode = "idle";
  const phases = [...state.running.values()].map((t) => t.phase);
  if (!state.connected || (state.status && !state.status.online)) mode = "offline";
  if (phases.length) mode = phases.some((p) => p === "tool") ? "working" : "thinking";
  if (voice.state === "listening") mode = "listening";
  if (voice.state === "speaking") mode = "speaking";
  if (state.approvals.length) mode = "alert";
  core.className = `core core-sm ${mode}`;
  emit("core", mode);
}

function handleEvent(ev) {
  switch (ev.type) {
    case "hello":
      (ev.pending_approvals || []).forEach(approvals.enqueue);
      break;
    case "task_started":
      state.running.set(ev.task_id, { conversation_id: ev.conversation_id, phase: "think" });
      break;
    case "tool_started":
    case "tool_status": {
      const task = state.running.get(ev.task_id);
      if (task) task.phase = ["done", "error", "blocked", "denied", "rejected"].includes(ev.status) ? "think" : "tool";
      break;
    }
    case "task_done":
      state.running.delete(ev.task_id);
      if (ev.status === "error" && ev.error) toast(ev.error, "bad", 7000);
      refreshStatus().catch(() => {});
      break;
    case "approval_required":
      approvals.enqueue(ev);
      break;
    case "approval_resolved":
      approvals.resolved(ev.approval_id);
      break;
    case "memory_saved":
      toast(`🧠 ${ev.created ? "Memória salva" : "Memória atualizada"}: ${ev.memory.content}`, "good");
      break;
    case "alert":
      toast(`🔔 ${ev.title} — ${ev.message}`, "warn", 10000);
      notify(ev.title, ev.message);
      break;
    case "briefing_ready":
      toast(`📰 Resumo pronto: ${ev.headline}`, "good", 7000);
      notify("Resumo do dia pronto", ev.headline);
      break;
    default:
      break;
  }
  updateCore();
  emit("live", ev);
}

/** Notificação do Windows quando a janela não está em foco (se você permitiu na tela Mundo). */
function notify(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted" || document.hasFocus()) return;
  try {
    const n = new Notification(`Sexta-Feira — ${title}`, { body, icon: "/static/favicon.svg", tag: `sexta-${title}` });
    n.onclick = () => { window.focus(); location.hash = "#/mundo"; n.close(); };
  } catch { /* alguns navegadores só permitem via service worker */ }
}

async function panic() {
  if (!confirm("Interromper todas as tarefas e mudar para o modo Restrito?")) return;
  try {
    const res = await api("/api/tasks/cancel_all", { method: "POST", body: { panic: true } });
    toast(`Parada de emergência: ${res.cancelled} tarefa(s) interrompida(s). Modo Restrito ativado.`, "warn", 6000);
    await refreshStatus();
  } catch (err) {
    toast(err.message, "bad");
  }
}

boot();
