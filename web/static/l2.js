/* Kastack L2 dashboard logic. Pure client-side rendering of the masked JSON API;
   the live assistant answer comes from /api/l2/ask (deterministic server engine). */

const PRIORITY_COLORS = { critical: "danger", high: "warning",
                          medium: "primary", low: "secondary" };
const ROUTE_COLORS = { blocked: "danger", ask_for_confirmation: "warning",
                       process_locally: "success" };

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function badge(text, cls) {
  return `<span class="badge bg-${cls || "secondary"}">${esc(text)}</span>`;
}

function confPct(c) {
  return Math.round((c == null ? 0 : c) * 100) + "%";
}

function confText(c) {
  return `<span class="small ${c >= 0.8 ? "text-success"
          : c >= 0.6 ? "text-warning" : "text-danger"}">${confPct(c)}</span>`;
}

async function getJSON(url) {
  const r = await fetch(url);
  return r.json();
}

function initStats() {
  getJSON("/api/l2/benchmark").then(d => {
    const s = d.summary || {};
    const b = d.benchmark || {};
    const card = (title, value, cls) =>
      `<div class="col"><div class="card"><div class="card-body py-2">
         <div class="small text-secondary">${title}</div>
         <div class="h5 mb-0 text-${cls || "light"}">${value}</div>
       </div></div></div>`;
    const html = [
      card("Messages processed", (s.corpus || {}).messages || "-"),
      card("Canonical items / groups", (s.items || 0) + " / " + (s.groups || 0)),
      card("Priority decisions", s.priority_decisions || "-"),
      card("Search speedup vs naive", (b.speedup_x || "-") + "x"),
      card("Top-1 retrieval agreement", (b.quality_top1 || b.quality || "-") +
           " naive == index"),
      card("Mean latency (index)",
           (b.mean_latency_ms_optimized || b.mean_latency_ms || "-") + " ms"),
    ].join("");
    document.getElementById("l2Stats").innerHTML = html;
  });
}

function initPriorityTable() {
  const table = document.getElementById("priorityTable").querySelector("tbody");
  const count = document.getElementById("priorityCount");
  const prFilter = document.getElementById("prFilter");
  const qPriority = document.getElementById("qPriority");

  async function render() {
    const params = new URLSearchParams();
    if (qPriority.value.trim()) params.set("q", qPriority.value.trim());
    let rows = await getJSON("/api/l2/priority?" + params.toString());
    if (prFilter.value) rows = rows.filter(r => r.priority === prFilter.value);
    table.innerHTML = rows.map(r => `<tr>
      <td class="small">${esc(r.message_id)}</td>
      <td class="small">${esc(r.item_id)}</td>
      <td>${badge(r.priority, PRIORITY_COLORS[r.priority])}</td>
      <td>${confText(r.confidence)}</td>
      <td class="small text-secondary">${esc(r.reason)}</td>
      <td class="small"><code>${(r.signals || []).join(", ")}</code></td>
    </tr>`).join("");
    count.textContent = `${rows.length} priority decisions (each per-message, full history)`;
  }
  prFilter.onchange = render;
  qPriority.oninput = render;
  render();
}

function initGroupTable() {
  const table = document.getElementById("groupTable").querySelector("tbody");
  const count = document.getElementById("groupCount");
  const qGroups = document.getElementById("qGroups");

  async function render() {
    const params = new URLSearchParams();
    if (qGroups.value.trim()) params.set("q", qGroups.value.trim());
    const rows = await getJSON("/api/l2/groups?" + params.toString());
    table.innerHTML = rows.map(r => `<tr>
      <td>${esc(r.group_id)}</td>
      <td>${esc(r.title)}</td>
      <td>${badge(r.status, r.status === "completed" ? "success"
                 : r.status === "cancelled" ? "secondary"
                 : r.status === "rescheduled" ? "info" : "primary")}</td>
      <td class="small">${(r.related_message_ids || []).length}</td>
      <td class="small">${esc(r.latest_deadline || "") || "&mdash;"}</td>
      <td class="small text-secondary" style="max-width:520px">
        ${esc((r.summary || "").slice(0, 260) + ((r.summary || "").length > 260 ? " …" : ""))}
      </td>
    </tr>`).join("");
    count.textContent = `${rows.length} groups (threads merged from related messages)`;
  }
  qGroups.oninput = render;
  render();
}

function initRouteTables() {
  const table = document.getElementById("routeTable").querySelector("tbody");
  const count = document.getElementById("routeCount");
  const scope = document.getElementById("routeScope");
  const filter = document.getElementById("routeFilter");

  async function render() {
    const params = new URLSearchParams();
    params.set("scope", scope.value);
    if (filter.value) params.set("route", filter.value);
    const rows = await getJSON("/api/l2/routing?" + params.toString());
    table.innerHTML = rows.map(r => `<tr>
      <td class="small">${esc(r.request_id)}</td>
      <td class="small">${esc(r.timestamp || "&mdash;")}</td>
      <td class="small">${esc(r.sender || "&mdash;")}</td>
      <td>${badge((ROUTE_COLORS[r.route] ? r.route : (r.route || "—")),
                   (r.route && ROUTE_COLORS[r.route]) ? ROUTE_COLORS[r.route]
                                                     : "secondary")}</td>
      <td>${confText(r.confidence)}</td>
      <td class="small text-secondary">${esc(r.reason)}</td>
      <td class="small"><code>${esc(r.masked_evidence || "")}</code></td>
    </tr>`).join("");
    count.textContent = `${rows.length} routing decisions (masked evidence only)`;
  }
  scope.onchange = render;
  filter.onchange = render;
  render();
}

function initDemoRoutes() {
  const table = document.getElementById("demoRouteTable").querySelector("tbody");
  getJSON("/api/l2/demo").then(d => {
    table.innerHTML = (d.routing || []).map(r => `<tr>
      <td class="small">${esc(r.request_id)}</td>
      <td>${badge(r.route, ROUTE_COLORS[r.route])}</td>
      <td class="small text-secondary">${esc(r.reason)}</td>
      <td class="small"><code>${esc(r.masked_evidence || "")}</code></td>
    </tr>`).join("");
  });
}

function initDemoItems() {
  const table = document.getElementById("demoItemTable").querySelector("tbody");
  getJSON("/api/l2/demo").then(d => {
    table.innerHTML = (d.items || []).map(r => `<tr>
      <td class="small">${esc(r.item_id)}</td>
      <td>${esc(r.title)}</td>
      <td>${badge(r.priority, PRIORITY_COLORS[r.priority])}</td>
      <td class="small">${esc(r.status)}</td>
      <td class="small">${(r.message_ids || []).join(", ")}</td>
    </tr>`).join("");
  });
}

function initPrecomputedAnswers() {
  const out = document.getElementById("answerList");
  getJSON("/api/l2/answers").then(d => {
    const routeOf = {};
    (d.query_routing || []).forEach(r => { routeOf[r.request_id] = r; });
    out.innerHTML = (d.answers || []).map(a => {
      const rt = routeOf[a.query_id];
      const rtBadge = rt ? ` ${badge(rt.route, ROUTE_COLORS[rt.route] || "secondary")}` : "";
      return `<div class="card mb-2">
        <div class="card-body py-2">
          <div class="d-flex justify-content-between align-items-center">
            <strong class="small">${esc(a.query_id)}</strong>
            <span>${badge(a.intent, "info")}${rtBadge}</span>
          </div>
          <div class="small mb-1">${esc(a.query)}</div>
          <code class="answer-card d-block small">${esc(a.final_answer)}</code>
          <div class="small text-secondary mt-1">
            ${esc(a.reason || "")}
            ${a.insufficient_evidence ? badge("insufficient evidence", "warning") : ""}
          </div>
          ${a.supporting_message_ids && a.supporting_message_ids.length
            ? `<div class="small mt-1"><span class="text-secondary">evidence:</span>
                 ${a.supporting_message_ids.map(esc).join(", ")}</div>` : ""}
        </div>
      </div>`;
    }).join("");
  });
}

function initBenchmark() {
  const out = document.getElementById("benchOut");
  getJSON("/api/l2/benchmark").then(d => {
    const s = d.summary || {};
    const b = d.benchmark || {};
    const docs = d.index_docs || [];
    const perType = {};
    docs.forEach(doc => { perType[doc.kind] = (perType[doc.kind] || 0) + 1; });
    const card = (title, value, note) =>
      `<div class="col-md-3"><div class="card h-100"><div class="card-body">
         <div class="small text-secondary">${title}</div>
         <div class="h4 mb-1">${value}</div>
         <div class="small text-secondary">${note || ""}</div>
       </div></div></div>`;
    out.innerHTML =
      card("Latency per query (index)",
           (b.mean_latency_ms_optimized || b.mean_latency_ms || "-") + " ms",
           "vs naive-search baseline") +
      card("Speedup vs naive", (b.speedup_x || "-") + "x", "same TF-IDF formula") +
      card("Top-1 quality", b.quality_top1 || b.quality || "-",
           "non-empty naive hits that the index agrees on") +
      card("Index size", (b.size_bytes || 0).toLocaleString() + " B", "on disk") +
      `<div class="col-12"><div class="card"><div class="card-body pb-1">
         <h6 class="mb-2">Fair comparison</h6>
         <p class="small text-secondary mb-2">
           Both the naive matcher and the sparse index use the identical TF-IDF
           formula over the same documents (${docs.length} docs, ${s.index ? s.index.terms : "-"} terms);
           only the precomputation differs, so the speedup measures the
           precomputation win, not a formula shortcut.</p>
         <div class="small mb-2">Indexed documents:
           ${Object.entries(perType).map(([k, v]) =>
             badge(k + " " + v, k === "message" ? "primary" : "info")).join(" ")}</div>
       </div></div></div>`;
  });
}

function initAsk() {
  const box = document.getElementById("askBox");
  const btn = document.getElementById("askBtn");
  const out = document.getElementById("askOut");
  const quick = document.getElementById("quickAsk");
  if (!box) return;

  getJSON("/api/l2/answers").then(d => {
    quick.innerHTML = `<option value="">demo queries DQ01-DQ09…</option>` +
      (d.answers || []).filter(a => (a.query_id || "").startsWith("DQ"))
        .map(a => `<option value="${esc(a.query)}">${esc(a.query_id)}</option>`)
        .join("");
  });
  quick.onchange = () => {
    if (quick.value) { box.value = quick.value; ask(); }
  };

  async function ask() {
    const q = box.value.trim();
    if (!q) return;
    btn.disabled = true;
    btn.textContent = "Thinking…";
    try {
      const d = await getJSON("/api/l2/ask?q=" + encodeURIComponent(q));
      if (d.error) {
        out.innerHTML = `<div class="alert alert-danger mb-0">${esc(d.error)}</div>`;
        return;
      }
      const a = d.answer;
      const rt = d.routing || {};
      out.innerHTML = `<div class="row g-2">
        <div class="col-12">
          <span>${badge(a.intent, "info")}</span>
          <span>${badge(rt.route || "ok", ROUTE_COLORS[rt.route] || "success")}</span>
          ${a.insufficient_evidence ? badge("insufficient evidence", "warning") : ""}
        </div>
        <div class="col-12">
          <code class="answer-card d-block small p-2">${esc(rt.final_answer || a.final_answer)}</code>
        </div>
        <div class="col-12 small text-secondary">${esc(a.reason || "")}</div>
        <div class="col-12 small">
          ${a.supporting_message_ids && a.supporting_message_ids.length
            ? `<span class="text-secondary">evidence:</span>
               <code>${a.supporting_message_ids.map(esc).join(", ")}</code>`
            : ""}
        </div>
      </div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Ask";
    }
  }
  btn.onclick = ask;
  box.addEventListener("keydown", e => { if (e.key === "Enter") ask(); });
}

initStats();
initPriorityTable();
initGroupTable();
initRouteTables();
initDemoRoutes();
initDemoItems();
initPrecomputedAnswers();
initBenchmark();
initAsk();