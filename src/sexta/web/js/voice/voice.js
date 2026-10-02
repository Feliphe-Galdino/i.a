// Controlador de voz da Sexta-Feira (global — funciona em qualquer tela).
//
// Estados: off → idle (aguardando ativação) → listening (ouvindo o pedido)
//          → thinking (IA trabalhando) → speaking (respondendo em voz alta) → idle
//
// Ativação: "Olá, Sexta-Feira" (reconhecimento de fala do navegador, pt-BR),
//           duas palmas (detector local em AudioWorklet) ou o botão do microfone.
// Fala: speechSynthesis do navegador (vozes do Windows/Edge/Chrome — gratuitas).
//
// Privacidade: o reconhecimento do navegador envia o áudio ao serviço de fala do
// Google (Chrome) ou da Microsoft (Edge) enquanto escuta. Com "Olá, Sexta-Feira"
// desligado, o reconhecimento só liga DEPOIS das palmas ou do botão.

import { api, live, urlFlags } from "../api.js";
import { answerApproval } from "../approvals.js";
import { emit, on, state } from "../state.js";
import { toast } from "../ui.js";
import { chunkSentences, matchControl, matchWake, normalizeSpeech, shortenPaths, toSpeakable } from "./speech-text.js";

const KEY = "sexta.voice";
const DEFAULTS = {
  mode: "texto",          // texto | voz | ambos
  wake: true,             // escuta contínua de "Olá, Sexta-Feira"
  nameOnly: false,        // aceitar só "Sexta-Feira, …" no início da frase
  claps: true,            // ativação por duas palmas
  clapSensitivity: 0.5,
  voiceURI: "",
  rate: 1.05,
  pitch: 1.0,
  volume: 1.0,
};
const LISTEN_TIMEOUT_MS = 8000;
const APPROVAL_TIMEOUT_MS = 20000;

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const synth = window.speechSynthesis || null;

export const voice = {
  settings: { ...DEFAULTS },
  state: "off",
  error: "",
  transcript: "",
  supported: {
    recognition: Boolean(SR),
    synthesis: Boolean(synth),
    claps: Boolean(navigator.mediaDevices?.getUserMedia && window.AudioWorkletNode),
  },
};

let rec = null;
let recRunning = false;
let recBlocked = false;
let micWarned = false;
let backoff = 0;
let audioCtx = null;
let workletLoaded = false;
let clapNode = null;
let micStream = null;
let listenTimer = null;
let awaitingApproval = null;
let approvalRetries = 0;
let speakDoneTimer = null;
// Quando o motor de voz LOCAL (no PC, em Python) está ativo, o navegador não escuta:
// só espelha o estado e encaminha o botão do microfone para o servidor.
let proxy = false;

// ---------------------------------------------------------------------------
// Configurações (por navegador/janela)
// ---------------------------------------------------------------------------

function loadSettings() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KEY) || "null"); } catch { saved = null; }
  voice.settings = { ...DEFAULTS, ...(saved || {}) };
  return saved !== null;
}

export function saveVoiceSettings(patch) {
  const before = voice.settings;
  voice.settings = { ...before, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(voice.settings)); } catch { /* modo privado */ }
  const enabled = voice.settings.mode !== "texto";
  if (enabled && voice.state === "off") start();
  else if (!enabled && voice.state !== "off") stop();
  else if (enabled) {
    if (patch.claps !== undefined) (voice.settings.claps ? startClaps() : stopClaps());
    if (patch.clapSensitivity !== undefined) clapNode?.port.postMessage({ type: "sensitivity", value: voice.settings.clapSensitivity });
    if (patch.wake !== undefined) syncRecognition();
  }
  emit("voice-settings", voice.settings);
}

export const isVoiceEnabled = () => voice.settings.mode !== "texto";

// ---------------------------------------------------------------------------
// Estado e interface
// ---------------------------------------------------------------------------

const STATE_LABEL = {
  off: "Voz desligada",
  starting: "Preparando a voz…",
  idle: "Aguardando: “Olá, Sexta-Feira” ou duas palmas",
  listening: "Ouvindo…",
  transcribing: "Entendendo…",
  thinking: "Pensando…",
  speaking: "Falando…",
  error: "Voz com problema",
};
const BUTTON_LABEL = {
  off: "Voz", starting: "Iniciando", idle: "Pronta", listening: "Ouvindo", transcribing: "Entendendo",
  thinking: "Pensando", speaking: "Falando", error: "Voz",
};

function setState(next) {
  voice.state = next;
  if (next !== "listening") voice.transcript = "";
  emit("voice-state", next);
  renderUI();
  syncRecognition();
}

function setError(message) {
  voice.error = message;
  toast(message, "bad", 8000);
  renderUI();
}

function renderUI() {
  const btn = document.getElementById("voice-btn");
  const overlay = document.getElementById("voice-overlay");
  if (btn) {
    btn.dataset.state = voice.state;
    const where = proxy ? " (no PC)" : "";
    btn.title = voice.error ? `${STATE_LABEL[voice.state]} — ${voice.error}` : `${STATE_LABEL[voice.state] || voice.state}${where}`;
    btn.classList.toggle("has-error", Boolean(voice.error));
    btn.querySelector(".label").textContent = BUTTON_LABEL[voice.state] || "Voz";
  }
  if (overlay) {
    const visible = ["listening", "transcribing", "thinking", "speaking"].includes(voice.state);
    overlay.classList.toggle("hidden", !visible);
    overlay.dataset.state = voice.state;
    overlay.querySelector(".state").textContent = awaitingApproval && voice.state === "listening" ? "Diga “sim” ou “não”…" : STATE_LABEL[voice.state];
    overlay.querySelector(".transcript").textContent = voice.transcript;
  }
}

// ---------------------------------------------------------------------------
// Ciclo de vida
// ---------------------------------------------------------------------------

export function initVoice() {
  const hadSettings = loadSettings();
  if (urlFlags.voice && !hadSettings) {
    // Janela dedicada (inicia com o Windows): voz ligada por padrão.
    voice.settings.mode = "ambos";
    try { localStorage.setItem(KEY, JSON.stringify(voice.settings)); } catch { /* ignore */ }
  }
  document.getElementById("voice-btn")?.addEventListener("click", onButton);
  document.getElementById("voice-overlay")?.addEventListener("click", () => {
    if (voice.state === "speaking") stopSpeaking();
    else if (voice.state === "listening") deactivate();
  });
  // Sem o atalho da janela dedicada, o navegador só libera áudio após um clique.
  const unlock = () => { audioCtx?.resume?.(); };
  window.addEventListener("pointerdown", unlock);
  window.addEventListener("keydown", unlock);
  on("live", onLiveEvent);
  on("live", onServerVoiceEvent);
  on("voice-failed", (message) => { if (!proxy) say(`Não consegui enviar o pedido. ${message || ""}`); });
  on("status", (status) => applyServerVoice(status?.voice));
  if (synth) synth.onvoiceschanged = () => emit("voice-voices", listVoices());
  renderUI();
  applyServerVoice(state.status?.voice);
  if (!proxy && isVoiceEnabled() && serverEngine !== "desligado") start();
  // Ferramentas para o console do navegador (F12) e testes automatizados.
  window.sextaVoice = { voice, activate, say, simulateSpeech: (text, isFinal = true) => onResult(text, isFinal) };
}

function start() {
  voice.error = "";
  recBlocked = false;
  setState("idle");
  if (voice.settings.claps) startClaps();
  if (!SR) setError("Este navegador não reconhece fala. Use o Google Chrome ou o Microsoft Edge.");
}

function stop() {
  clearTimeout(listenTimer);
  awaitingApproval = null;
  stopClaps();
  stopSpeaking(false);
  voice.state = "off";
  syncRecognition();
  emit("voice-state", "off");
  renderUI();
}

function onButton() {
  if (proxy) {
    if (voice.state === "speaking") return api("/api/voice/stop", { method: "POST" }).catch(() => {});
    if (voice.state === "error" || voice.state === "off") {
      location.hash = "#/config";
      return null;
    }
    return api("/api/voice/activate", { method: "POST" }).catch((err) => toast(err.message, "bad"));
  }
  if (voice.state === "off") return saveVoiceSettings({ mode: voice.settings.mode === "texto" ? "ambos" : voice.settings.mode });
  if (voice.state === "speaking") return stopSpeaking();
  if (voice.state === "listening") return deactivate();
  activate("botão");
}

// ---------------------------------------------------------------------------
// Motor local (servidor): espelho do estado
// ---------------------------------------------------------------------------

let serverEngine = "";

export const isLocalEngine = () => proxy;

function applyServerVoice(info) {
  if (!info) return;
  serverEngine = info.engine;
  const wantProxy = info.engine === "local";
  if (wantProxy && !proxy) {
    if (voice.state !== "off") stop();
    proxy = true;
  } else if (!wantProxy && proxy) {
    proxy = false;
    voice.state = "off";
    if (isVoiceEnabled() && info.engine === "navegador") start();
  }
  if (proxy) mirror(info.state, info.error, voice.transcript);
}

function mirror(nextState, error = "", transcript = "") {
  const changed = voice.state !== nextState;
  voice.state = nextState;
  voice.error = error || "";
  voice.transcript = transcript || "";
  renderUI();
  if (changed) emit("voice-state", nextState);
}

function onServerVoiceEvent(ev) {
  if (!proxy) return;
  if (ev.type === "voice_state") mirror(ev.state, ev.error, ev.transcript);
  else if (ev.type === "voice_transcript") { voice.transcript = ev.text; renderUI(); }
  else if (ev.type === "voice_level") emit("voice-level", { peak: ev.peak, threshold: ev.threshold });
  else if (ev.type === "voice_clap") emit("voice-clap", ev);
  else if (ev.type === "voice_double_clap") emit("voice-double-clap", ev);
}

// ---------------------------------------------------------------------------
// Ativação e comandos
// ---------------------------------------------------------------------------

export function activate(source = "voz") {
  if (voice.state === "off") return;
  if (voice.state === "speaking") stopSpeaking(false);
  chime("on");
  setState("listening");
  resetListenTimer();
  emit("voice-activated", source);
}

function deactivate() {
  clearTimeout(listenTimer);
  if (voice.state === "listening") {
    chime("off");
    setState("idle");
  }
}

function resetListenTimer(ms = LISTEN_TIMEOUT_MS) {
  clearTimeout(listenTimer);
  listenTimer = setTimeout(() => {
    if (awaitingApproval) {
      awaitingApproval = null;
      say("Sem resposta. A ação continua aguardando confirmação na tela.");
      return;
    }
    if (voice.state === "listening") deactivate();
  }, ms);
}

function onResult(text, isFinal) {
  const transcript = String(text || "").trim();
  if (!transcript) return;

  if (voice.state === "speaking") {
    // Durante a fala, só aceitamos "silêncio"/"parar" (evita ouvir a própria voz).
    const control = isFinal ? matchControl(transcript) : null;
    if (control === "silence") stopSpeaking();
    if (control === "stop") { stopSpeaking(false); cancelRunningTasks(); }
    return;
  }

  if (awaitingApproval) {
    voice.transcript = transcript;
    renderUI();
    if (isFinal) handleApprovalAnswer(transcript);
    return;
  }

  if (voice.state === "listening") {
    voice.transcript = transcript;
    renderUI();
    resetListenTimer(isFinal ? LISTEN_TIMEOUT_MS : LISTEN_TIMEOUT_MS + 4000);
    if (!isFinal) return;
    const wake = matchWake(transcript, { nameOnly: true });
    const command = wake ? wake.command : transcript;
    if (command.trim()) handleCommand(command.trim());
    return;
  }

  if ((voice.state === "idle" || voice.state === "thinking") && voice.settings.wake) {
    const wake = matchWake(transcript, { nameOnly: voice.settings.nameOnly });
    if (!wake) return;
    activate("voz");
    if (isFinal && wake.command) handleCommand(wake.command);
  }
}

function handleCommand(command) {
  clearTimeout(listenTimer);
  const control = matchControl(command);
  if (control === "silence") { setState("idle"); return; }
  if (control === "stop" || (control === "no" && normalizeSpeech(command).startsWith("cancel"))) {
    const count = cancelRunningTasks();
    say(count ? "Certo, interrompi." : "Não há nada em andamento.");
    return;
  }
  chime("ok");
  setState("thinking");
  state.pendingVoiceCommand = command;
  if (!location.hash.startsWith("#/chat")) location.hash = "#/chat";
  emit("voice-command", command);
}

function cancelRunningTasks() {
  let count = 0;
  for (const taskId of state.running.keys()) {
    live.send({ type: "cancel", task_id: taskId });
    count++;
  }
  return count;
}

// ---------------------------------------------------------------------------
// Eventos do núcleo: respostas faladas e confirmações por voz
// ---------------------------------------------------------------------------

function onLiveEvent(ev) {
  if (proxy || !isVoiceEnabled()) return;
  if (ev.type === "task_done") {
    const shouldSpeak = voice.settings.mode === "voz" || ev.channel === "voz";
    if (!shouldSpeak) {
      if (voice.state === "thinking" && state.running.size === 0) setState("idle");
      return;
    }
    if (ev.status === "done" || ev.status === "refused") say(ev.text || "Pronto.");
    else if (ev.status === "cancelled") say("Tarefa interrompida.");
    else if (ev.status === "blocked") say("Orçamento diário atingido. Ajuste nas configurações.");
    else say(`Não consegui concluir. ${ev.error || ""}`);
  } else if (ev.type === "approval_required") {
    handleApprovalRequest(ev);
  } else if (ev.type === "approval_resolved" && awaitingApproval?.approval_id === ev.approval_id) {
    awaitingApproval = null;
    if (voice.state === "listening") setState("idle");
  }
}

function handleApprovalRequest(ev) {
  const summary = shortenPaths(ev.summary || ev.tool);
  if (ev.risk === "critical") {
    say(`Atenção: ação crítica. ${summary}. Por segurança, confirme na tela.`);
    return;
  }
  awaitingApproval = ev;
  approvalRetries = 0;
  say(`Preciso da sua confirmação: ${summary}. Diga sim ou não.`, () => {
    if (!awaitingApproval) return;
    setState("listening");
    resetListenTimer(APPROVAL_TIMEOUT_MS);
  });
}

function handleApprovalAnswer(text) {
  const control = matchControl(text);
  const req = awaitingApproval;
  if (control === "yes") {
    awaitingApproval = null;
    answerApproval(req.approval_id, true);
    chime("ok");
    setState("thinking");
  } else if (control === "no" || control === "stop") {
    awaitingApproval = null;
    answerApproval(req.approval_id, false);
    say("Tudo bem, não vou fazer.");
  } else if (approvalRetries++ < 1) {
    say("Não entendi. Diga sim ou não.", () => { if (awaitingApproval) { setState("listening"); resetListenTimer(APPROVAL_TIMEOUT_MS); } });
  } else {
    awaitingApproval = null;
    say("Deixei a confirmação na tela.");
  }
}

// ---------------------------------------------------------------------------
// Reconhecimento de fala (Web Speech API)
// ---------------------------------------------------------------------------

function recognitionWanted() {
  if (voice.state === "off" || !SR || recBlocked) return false;
  return voice.settings.wake || voice.state === "listening" || Boolean(awaitingApproval);
}

function createRecognition() {
  const r = new SR();
  r.lang = "pt-BR";
  r.continuous = true;
  r.interimResults = true;
  r.maxAlternatives = 1;
  r.onstart = () => {
    recRunning = true;
    if (micWarned && backoff === 5000) backoff = 0;
  };
  r.onresult = (event) => {
    if (micWarned) {
      micWarned = false;
      voice.error = "";
      renderUI();
    }
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      onResult(result[0].transcript, result.isFinal);
    }
    backoff = 0;
  };
  r.onerror = (event) => {
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      recBlocked = true;
      setError("O microfone foi bloqueado. Clique no cadeado da barra de endereço e permita o microfone.");
    } else if (event.error === "audio-capture") {
      // Pode ser passageiro (microfone ocupado ou desconectado): tenta de novo depois.
      backoff = 5000;
      if (!micWarned) {
        micWarned = true;
        setError("Não consegui acessar o microfone. Verifique se ele está conectado — vou tentar de novo.");
      }
    } else if (event.error === "network") {
      backoff = Math.min(30000, (backoff || 1000) * 2);
    }
  };
  r.onend = () => {
    recRunning = false;
    if (recognitionWanted()) setTimeout(syncRecognition, backoff || 300);
  };
  return r;
}

function syncRecognition() {
  if (!SR) return;
  if (recognitionWanted()) {
    if (recRunning) return;
    rec = rec || createRecognition();
    try {
      rec.start();
      recRunning = true;
    } catch {
      /* já iniciado */
    }
  } else if (recRunning && rec) {
    try { rec.abort(); } catch { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Palmas (AudioWorklet local)
// ---------------------------------------------------------------------------

function getAudioContext() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    audioCtx = new Ctx();
  }
  return audioCtx;
}

async function startClaps() {
  if (clapNode || !voice.supported.claps || voice.state === "off") return;
  try {
    const ctx = getAudioContext();
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 },
    });
    if (!workletLoaded) {
      await ctx.audioWorklet.addModule("/static/js/voice/clap-worklet.js");
      workletLoaded = true;
    }
    const source = ctx.createMediaStreamSource(micStream);
    clapNode = new AudioWorkletNode(ctx, "clap-detector", { processorOptions: { sensitivity: voice.settings.clapSensitivity } });
    const sink = ctx.createGain();
    sink.gain.value = 0; // mantém o grafo ativo sem tocar o som do microfone
    source.connect(clapNode).connect(sink).connect(ctx.destination);
    clapNode.port.onmessage = ({ data }) => {
      if (data.type === "level") emit("voice-level", data);
      else if (data.type === "clap") emit("voice-clap", data);
      else if (data.type === "double") onDoubleClap();
    };
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
  } catch (err) {
    stopClaps();
    setError(err?.name === "NotAllowedError" ? "Permita o microfone para ativar por palmas." : `Palmas indisponíveis: ${err?.message || err}`);
  }
}

function stopClaps() {
  try { clapNode?.disconnect(); } catch { /* ignore */ }
  clapNode = null;
  micStream?.getTracks().forEach((track) => track.stop());
  micStream = null;
}

function onDoubleClap() {
  emit("voice-double-clap");
  if (voice.state === "speaking") return stopSpeaking();
  if (voice.state === "idle" || voice.state === "thinking") activate("palmas");
}

// ---------------------------------------------------------------------------
// Fala (speechSynthesis) e sinais sonoros
// ---------------------------------------------------------------------------

export function listVoices() {
  if (!synth) return [];
  const voices = synth.getVoices();
  const portuguese = voices.filter((v) => /^pt/i.test(v.lang));
  return portuguese.length ? portuguese : voices;
}

function pickVoice() {
  const voices = synth ? synth.getVoices() : [];
  if (voice.settings.voiceURI) {
    const chosen = voices.find((v) => v.voiceURI === voice.settings.voiceURI);
    if (chosen) return chosen;
  }
  const br = voices.filter((v) => /^pt[-_]?BR/i.test(v.lang));
  return (
    br.find((v) => /Francisca|Thalita|Antonio/i.test(v.name)) ||
    br.find((v) => /Google/i.test(v.name)) ||
    br[0] ||
    voices.find((v) => /^pt/i.test(v.lang)) ||
    null
  );
}

/** Fala um texto (Markdown é convertido). onDone roda ao terminar ou ser interrompido. */
export function say(text, onDone) {
  const spoken = toSpeakable(text);
  if (!synth || !spoken || voice.state === "off") {
    if (voice.state !== "off") setState(awaitingApproval ? "listening" : "idle");
    onDone?.();
    return;
  }
  clearTimeout(speakDoneTimer);
  synth.cancel();
  const chosen = pickVoice();
  const chunks = chunkSentences(spoken);
  setState("speaking");
  chunks.forEach((chunk, index) => {
    const utterance = new SpeechSynthesisUtterance(chunk);
    utterance.lang = chosen?.lang || "pt-BR";
    if (chosen) utterance.voice = chosen;
    utterance.rate = voice.settings.rate;
    utterance.pitch = voice.settings.pitch;
    utterance.volume = voice.settings.volume;
    if (index === chunks.length - 1) {
      utterance.onend = utterance.onerror = () => {
        // pequena pausa para o reconhecedor não ouvir o fim da própria fala
        speakDoneTimer = setTimeout(() => {
          if (voice.state === "speaking") setState(awaitingApproval ? "listening" : "idle");
          onDone?.();
        }, 350);
      };
    }
    synth.speak(utterance);
  });
}

export function stopSpeaking(toIdle = true) {
  clearTimeout(speakDoneTimer);
  synth?.cancel();
  if (toIdle && voice.state === "speaking") setState("idle");
}

/** Testa a voz atual (usado nas Configurações). */
export function testVoice() {
  if (proxy) {
    api("/api/voice/say", { method: "POST", body: { text: "Olá! Eu sou a Sexta-Feira, falando direto do seu computador." } })
      .catch((err) => toast(err.message, "bad"));
    return;
  }
  if (voice.state === "off") {
    if (!synth) return;
    const u = new SpeechSynthesisUtterance("Olá! Eu sou a Sexta-Feira. Ative a voz para conversar comigo.");
    const chosen = pickVoice();
    if (chosen) u.voice = chosen;
    u.rate = voice.settings.rate;
    u.pitch = voice.settings.pitch;
    synth.cancel();
    synth.speak(u);
    return;
  }
  say("Olá! Eu sou a Sexta-Feira. Estou pronta para ajudar.");
}

function chime(kind) {
  const ctx = getAudioContext();
  if (!ctx || ctx.state === "closed") return;
  const notes = { on: [660, 990], ok: [880], off: [660, 440] }[kind] || [880];
  const now = ctx.currentTime;
  notes.forEach((freq, i) => {
    const start = now + i * 0.09;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.16, start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.13);
    osc.connect(gain).connect(ctx.destination);
    osc.start(start);
    osc.stop(start + 0.15);
  });
}
