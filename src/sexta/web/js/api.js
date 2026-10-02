// Comunicação com o núcleo: REST (fetch) + WebSocket com reconexão automática.

const TOKEN_KEY = "sexta.token";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}

export function setToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* modo privado: token só na memória */ }
  memoryToken = token;
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
  memoryToken = "";
}

let memoryToken = "";
const token = () => memoryToken || getToken();

/** Parâmetros lidos da URL na abertura (ex.: ?voz=1 da janela que inicia com o Windows). */
export const urlFlags = { voice: false };

/** Captura ?token= da URL (link impresso no terminal) e limpa a barra de endereços. */
export function captureTokenFromUrl() {
  const url = new URL(window.location.href);
  const value = url.searchParams.get("token");
  urlFlags.voice = url.searchParams.get("voz") === "1";
  if (value) setToken(value);
  if (value || url.searchParams.has("voz")) {
    url.searchParams.delete("token");
    url.searchParams.delete("voz");
    window.history.replaceState(null, "", url.pathname + url.hash);
  }
  memoryToken = memoryToken || getToken();
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = { Authorization: `Bearer ${token()}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    let detail = res.statusText;
    try { const data = await res.json(); detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail); } catch { /* sem corpo */ }
    throw new ApiError(res.status, detail);
  }
  if (raw) return res;
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res.text();
}

/** Cliente WebSocket com fila de envio, reconexão exponencial e assinantes. */
export class Live {
  constructor() {
    this.listeners = new Set();
    this.statusListeners = new Set();
    this.queue = [];
    this.retry = 0;
    this.connected = false;
    this.stopped = false;
  }

  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token())}`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.connected = true;
      this.statusListeners.forEach((fn) => fn(true));
      while (this.queue.length) ws.send(JSON.stringify(this.queue.shift()));
      clearInterval(this.pinger);
      this.pinger = setInterval(() => this.send({ type: "ping" }), 25000);
    };
    ws.onmessage = (msg) => {
      let event;
      try { event = JSON.parse(msg.data); } catch { return; }
      this.listeners.forEach((fn) => { try { fn(event); } catch (err) { console.error(err); } });
    };
    ws.onclose = (ev) => {
      this.connected = false;
      clearInterval(this.pinger);
      this.statusListeners.forEach((fn) => fn(false, ev.code));
      if (this.stopped || ev.code === 4401) return;
      const delay = Math.min(15000, 500 * 2 ** this.retry++);
      setTimeout(() => this.connect(), delay);
    };
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(payload));
    else this.queue.push(payload);
  }

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  onStatus(fn) { this.statusListeners.add(fn); return () => this.statusListeners.delete(fn); }
}

export const live = new Live();
