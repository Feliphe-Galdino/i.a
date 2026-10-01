// Atividade: tarefas e registro de auditoria de tudo o que a Sexta-Feira fez.

import { api } from "../api.js";
import { on } from "../state.js";
import { fill, fmt, h, riskTag, TASK_STATUS, toast } from "../ui.js";

const EVENTS = {
  "": "Todos os eventos",
  tool_executed: "Ferramentas executadas",
  tool_decision: "Decisões de permissão",
  tool_approval: "Confirmações",
  tool_blocked: "Bloqueios de segurança",
  settings_changed: "Configurações alteradas",
  panic: "Parada de emergência",
};

const DECISION = { allow: "permitido", ask: "perguntar", deny: "negado", approved: "aprovado", rejected: "recusado" };

export function mount(root) {
  const filter = h("select", { "aria-label": "Filtrar eventos" }, Object.entries(EVENTS).map(([v, l]) => h("option", { value: v }, l)));
  const tasksBody = h("tbody");
  const auditBody = h("tbody");
  const page = h("div", { class: "page" },
    h("h1", { class: "page-title" }, "Atividade e auditoria"),
    h("section", { class: "panel", style: { marginBottom: "16px" } },
      h("div", { class: "panel-head" }, "Tarefas"),
      h("div", { class: "panel-body table-wrap" },
        h("table", { class: "data" },
          h("thead", {}, h("tr", {}, ["Início", "Status", "Pedido", "Agente", "Modelo", "Custo", ""].map((c) => h("th", {}, c)))),
          tasksBody))),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, "Registro de auditoria", filter),
      h("div", { class: "panel-body table-wrap" },
        h("table", { class: "data" },
          h("thead", {}, h("tr", {}, ["Quando", "Evento", "Ferramenta", "Risco", "Decisão", "Resultado", "Resumo"].map((c) => h("th", {}, c)))),
          auditBody))));
  root.append(page);
  filter.addEventListener("change", loadAudit);

  async function loadTasks() {
    try {
      const tasks = await api("/api/tasks?limit=50");
      fill(tasksBody, tasks.length ? tasks.map((t) => h("tr", {},
        h("td", { class: "mono" }, fmt.time(t.started_at)),
        h("td", {}, h("span", { class: `tag ${t.status === "done" ? "green" : t.running ? "amber" : ["error", "refused"].includes(t.status) ? "red" : ""}` }, TASK_STATUS[t.status] || t.status)),
        h("td", { class: "summary", title: (t.reasons || []).join(" · ") }, t.input_preview, t.error ? h("div", { class: "error-text" }, t.error) : null),
        h("td", {}, t.agent || ""),
        h("td", { class: "mono" }, `${t.model || ""}${t.effort ? ` (${t.effort})` : ""}`),
        h("td", { class: "mono" }, fmt.usd(t.cost_usd)),
        h("td", {}, t.running ? h("button", { class: "btn danger small", onclick: () => cancel(t.id) }, "Parar") : null)))
        : h("tr", {}, h("td", { colspan: 7, class: "empty" }, "Nenhuma tarefa ainda.")));
    } catch (err) { toast(err.message, "bad"); }
  }

  async function loadAudit() {
    const params = new URLSearchParams({ limit: "200" });
    if (filter.value) params.set("event", filter.value);
    try {
      const rows = await api(`/api/audit?${params}`);
      fill(auditBody, rows.length ? rows.map((r) => h("tr", {},
        h("td", { class: "mono" }, fmt.time(r.ts)),
        h("td", {}, r.event),
        h("td", { class: "mono" }, r.tool || ""),
        h("td", {}, r.risk ? riskTag(r.risk) : ""),
        h("td", {}, r.decision ? h("span", { class: `tag ${["deny", "rejected"].includes(r.decision) ? "red" : r.decision === "ask" ? "amber" : "green"}` }, DECISION[r.decision] || r.decision) : ""),
        h("td", {}, r.success === null ? "" : r.success ? "✔" : "✖", r.duration_ms !== null ? h("span", { class: "hint" }, ` ${r.duration_ms} ms`) : null),
        h("td", { class: "summary" }, r.detail.summary || r.detail.reason || (r.detail.changes ? JSON.stringify(r.detail.changes) : ""))))
        : h("tr", {}, h("td", { colspan: 7, class: "empty" }, "Nenhum evento registrado.")));
    } catch (err) { toast(err.message, "bad"); }
  }

  async function cancel(id) {
    try { await api(`/api/tasks/${id}/cancel`, { method: "POST" }); setTimeout(loadTasks, 300); } catch (err) { toast(err.message, "bad"); }
  }

  loadTasks();
  loadAudit();
  const off = on("live", (ev) => {
    if (ev.type === "task_done" || ev.type === "task_started") loadTasks();
    if (ev.type === "tool_status" && ["done", "error", "blocked", "denied", "rejected"].includes(ev.status)) loadAudit();
  });
  return () => off();
}
