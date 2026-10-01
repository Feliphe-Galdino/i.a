// Estado global mínimo da interface + barramento de eventos da UI.

export const state = {
  status: null,          // /api/status
  settings: null,        // /api/settings
  running: new Map(),    // task_id -> { conversation_id, phase }
  approvals: [],         // pedidos pendentes
  connected: false,
  currentConversation: sessionGet("sexta.conv") || null,
};

const target = new EventTarget();

export function emit(name, detail) { target.dispatchEvent(new CustomEvent(name, { detail })); }
export function on(name, fn) {
  const handler = (e) => fn(e.detail);
  target.addEventListener(name, handler);
  return () => target.removeEventListener(name, handler);
}

export function setCurrentConversation(id) {
  state.currentConversation = id;
  sessionSet("sexta.conv", id || "");
}

function sessionGet(key) { try { return sessionStorage.getItem(key); } catch { return null; } }
function sessionSet(key, value) { try { sessionStorage.setItem(key, value); } catch { /* ignore */ } }
