// Modal de confirmação de ações sensíveis (aparece em qualquer tela).

import { live } from "./api.js";
import { state, emit } from "./state.js";
import { h, clear, fmt, riskTag } from "./ui.js";

let current = null;
let timerId = null;

export function enqueue(request) {
  if (state.approvals.some((a) => a.approval_id === request.approval_id)) return;
  state.approvals.push({ ...request, receivedAt: Date.now() });
  emit("approvals", state.approvals);
  showNext();
}

export function resolved(approvalId) {
  state.approvals = state.approvals.filter((a) => a.approval_id !== approvalId);
  emit("approvals", state.approvals);
  if (current && current.approval_id === approvalId) close();
  showNext();
}

function answer(approved) {
  if (!current) return;
  live.send({ type: "approval", approval_id: current.approval_id, approved });
  resolved(current.approval_id);
}

function close() {
  clearInterval(timerId);
  current = null;
  clear(document.getElementById("modal-root"));
  document.removeEventListener("keydown", onKey);
}

function onKey(e) {
  if (e.key === "Escape") answer(false);
}

function showNext() {
  if (current || !state.approvals.length) return;
  current = state.approvals[0];
  const req = current;
  const critical = req.risk === "critical";
  const timer = h("span", { class: "timer" });
  const details = { ...(req.details || {}) };
  const preview = details.preview;
  delete details.preview;

  const approveBtn = h("button", { class: `btn ${critical ? "danger" : "warn"}`, onclick: () => answer(true) }, "Aprovar");
  const modal = h(
    "div",
    { class: `modal panel ${critical ? "critical" : ""}`, role: "alertdialog", "aria-modal": "true", "aria-labelledby": "appr-title" },
    h("h3", { id: "appr-title" }, critical ? "⚠ AÇÃO CRÍTICA — CONFIRMAÇÃO" : "CONFIRMAÇÃO NECESSÁRIA"),
    h("div", { class: "row", style: { display: "flex", gap: "6px", flexWrap: "wrap" } },
      h("span", { class: "tag cyan" }, req.tool), riskTag(req.risk), h("span", { class: "tag" }, req.capability)),
    h("p", { class: "summary" }, req.summary),
    h("p", { class: "hint" }, req.reason),
    preview ? h("details", { open: true }, h("summary", { class: "hint" }, "Prévia do conteúdo"), h("pre", {}, preview)) : null,
    h("details", {}, h("summary", { class: "hint" }, "Detalhes técnicos"), h("pre", {}, fmt.json(details))),
    h("div", { class: "actions" }, timer,
      h("button", { class: "btn", onclick: () => answer(false) }, "Negar"),
      approveBtn),
  );
  const root = clear(document.getElementById("modal-root"));
  root.append(h("div", { class: "modal-backdrop" }, modal));
  document.addEventListener("keydown", onKey);
  approveBtn.focus();

  const deadline = req.receivedAt + (req.timeout_s || 300) * 1000;
  const tick = () => {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    timer.textContent = `Negado automaticamente em ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left <= 0) resolved(req.approval_id);
  };
  tick();
  timerId = setInterval(tick, 1000);
}
