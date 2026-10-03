// Painel: sistema, consumo de API, tarefas, memória e atividade recente.

import { api } from "../api.js";
import { on, state } from "../state.js";
import { clear, fmt, h, riskTag, TASK_STATUS } from "../ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function gauge(label, value) {
  const r = 40;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  const valueCircle = svg("circle", { class: "value", cx: 48, cy: 48, r, "stroke-dasharray": circ, "stroke-dashoffset": circ * (1 - pct / 100) });
  const text = svg("text", { x: 48, y: 54, "text-anchor": "middle" });
  text.textContent = `${Math.round(pct)}%`;
  const root = svg("svg", { viewBox: "0 0 96 96", role: "img", "aria-label": `${label}: ${Math.round(pct)}%` });
  root.append(svg("circle", { class: "track", cx: 48, cy: 48, r }), valueCircle, text);
  return h("div", { class: `gauge ${pct >= 90 ? "bad" : pct >= 75 ? "warn" : ""}` }, root, h("span", { class: "lbl" }, label));
}

/** Barra do uso de uma janela do plano (0–100%), com o horário em que renova. */
function planMeter(label, window) {
  if (!window) return h("div", { class: "hint" }, `${label}: aparece depois da primeira resposta da IA.`);
  const pct = Math.round((window.utilization || 0) * 100);
  const resets = window.resetsAt ? new Date(window.resetsAt * 1000).toLocaleString("pt-BR", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "";
  return h("div", {},
    h("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "13px" } },
      h("span", {}, label), h("span", {}, `${pct}%${resets ? ` · renova ${resets}` : ""}`)),
    h("div", { class: `bar ${pct >= 90 ? "bad" : pct >= 75 ? "warn" : ""}`, role: "img", "aria-label": `${label}: ${pct}% usado` },
      h("span", { style: { width: `${pct}%` } })));
}

function card(title, span, ...body) {
  return h("section", { class: `panel ${span}` }, h("div", { class: "panel-head" }, title), h("div", { class: "panel-body" }, ...body));
}

export function mount(root) {
  const page = h("div", { class: "page" }, h("h1", { class: "page-title" }, "Painel de controle"));
  const grid = h("div", { class: "grid" });
  page.append(grid);
  root.append(page);

  async function render() {
    const s = state.status;
    let usage = { by_model: [], total_cost_usd: 0, requests: 0 };
    let tasks = [];
    let audit = [];
    try {
      [usage, tasks, audit] = await Promise.all([api("/api/usage?days=1"), api("/api/tasks?limit=8"), api("/api/audit?limit=8&event=tool_executed")]);
    } catch { /* mostra o que houver */ }
    if (!s) return;
    const sys = s.system;
    const ratio = s.daily_budget_usd ? Math.min(1, s.spent_today_usd / s.daily_budget_usd) : 0;

    clear(grid).append(
      card("Sistema", "span-5",
        h("div", { class: "gauges" }, gauge("CPU", sys.cpu_percentual), gauge("Memória", sys.memoria_percentual), gauge("Disco", sys.disco_percentual)),
        h("dl", { class: "kv", style: { marginTop: "14px" } },
          h("dt", {}, "Sistema"), h("dd", {}, sys.sistema),
          h("dt", {}, "Núcleos"), h("dd", {}, sys.cpu_nucleos),
          h("dt", {}, "RAM livre"), h("dd", {}, `${sys.memoria_disponivel_gb} / ${sys.memoria_total_gb} GB`),
          h("dt", {}, "Disco livre"), h("dd", {}, `${sys.disco_livre_gb} GB`),
          h("dt", {}, "Ligado desde"), h("dd", {}, sys.ligado_desde),
          sys.bateria ? [h("dt", {}, "Bateria"), h("dd", {}, `${sys.bateria.percentual}%${sys.bateria.carregando ? " ⚡" : ""}`)] : null)),

      s.provider === "claude-code"
        ? card("Uso do plano Claude Pro", "span-4",
          planMeter("Limite de 5 horas", s.plan?.five_hour),
          planMeter("Limite semanal", s.plan?.seven_day),
          h("p", { class: "hint" }, "Assinatura: sem custo por uso. Quando o limite acaba, a IA pausa até a renovação; voz, Mundo, memória e alertas continuam."),
          usage.by_model.length
            ? h("dl", { class: "kv" }, usage.by_model.map((m) => [
              h("dt", {}, m.model), h("dd", {}, `${m.requests} req · ${fmt.num(m.output_tokens)} tok`)]))
            : h("p", { class: "empty" }, "Nenhuma chamada de IA hoje."))
        : card("Consumo de API hoje", "span-4",
        h("div", { class: "big-number" }, fmt.usd(s.spent_today_usd)),
        h("div", { class: "hint" }, `de ${fmt.usd(s.daily_budget_usd)} de orçamento diário`),
        h("div", { class: `bar ${ratio >= 1 ? "bad" : ratio >= 0.8 ? "warn" : ""}` }, h("span", { style: { width: `${ratio * 100}%` } })),
        usage.by_model.length
          ? h("dl", { class: "kv" }, usage.by_model.map((m) => [
            h("dt", {}, m.model), h("dd", {}, `${m.requests} req · ${fmt.num(m.output_tokens)} tok · ${fmt.usd(m.cost_usd)}`)]))
          : h("p", { class: "empty" }, "Nenhuma chamada de IA hoje.")),

      card("Estado", "span-3",
        h("dl", { class: "kv" },
          h("dt", {}, "Provedor"), h("dd", {}, s.online ? (s.provider_label || "Claude") : "Offline"),
          h("dt", {}, "Autonomia"), h("dd", {}, s.autonomy_name),
          h("dt", {}, "Tarefas ativas"), h("dd", {}, s.running_tasks.length),
          h("dt", {}, "Aprovações"), h("dd", {}, s.pending_approvals),
          h("dt", {}, "Clientes"), h("dd", {}, s.clients),
          h("dt", {}, "Memórias"), h("dd", {}, s.memory.total))),

      card("Tarefas recentes", "span-7",
        tasks.length ? h("ul", { class: "list" }, tasks.map((t) => h("li", {},
          h("span", { class: `tag ${t.status === "done" ? "green" : t.status === "running" ? "amber" : t.status === "error" ? "red" : ""}` }, TASK_STATUS[t.status] || t.status),
          h("span", { class: "grow", title: t.input_preview }, t.input_preview),
          t.model ? h("span", { class: "tag" }, t.model.replace("claude-", "")) : null,
          h("span", { class: "time" }, `${fmt.ago(t.started_at)}${t.cost_usd ? ` · ${fmt.usd(t.cost_usd)}` : ""}`))))
          : h("p", { class: "empty" }, "Nenhuma tarefa ainda.")),

      card("Memória", "span-5",
        h("div", { class: "big-number" }, s.memory.total),
        h("div", { class: "hint" }, "fatos aprendidos"),
        Object.entries(s.memory.by_category).map(([cat, n]) => h("div", {},
          h("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "13px" } }, h("span", {}, cat), h("span", {}, n)),
          h("div", { class: "bar" }, h("span", { style: { width: `${(n / Math.max(1, s.memory.total)) * 100}%` } }))))),

      card("Ações recentes", "span-7",
        audit.length ? h("ul", { class: "list" }, audit.map((a) => h("li", {},
          h("span", { class: `tag ${a.success ? "green" : "red"}` }, a.success ? "ok" : "falha"),
          h("span", { class: "tag cyan" }, a.tool), riskTag(a.risk),
          h("span", { class: "grow", title: a.detail.summary || "" }, a.detail.summary || ""),
          h("span", { class: "time" }, fmt.ago(a.ts)))))
          : h("p", { class: "empty" }, "Nenhuma ação executada ainda.")),

      card("Próximos módulos", "span-5 soon",
        h("div", { class: "roadmap" },
          h("div", {}, h("span", { class: "tag violet" }, "Fase 4"), "Projetos com memória própria e aprendizado com 👍/👎"),
          h("div", {}, h("span", { class: "tag violet" }, "Fase 5"), "Rotinas agendadas e integrações (agenda, e-mail, GitHub)"),
          h("div", {}, h("span", { class: "tag violet" }, "Fase 6"), "App com ícone na bandeja e acesso pelo celular"))),
    );
  }

  render();
  const offStatus = on("status", render);
  return () => offStatus();
}
