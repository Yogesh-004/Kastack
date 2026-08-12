/* Kastack dashboard logic. Pure client-side rendering of the masked JSON API. */

const CATEGORY_COLORS = {
  action_required: "danger",
  meeting_or_event: "primary",
  personal_information: "info",
  general_information: "secondary",
  promotional: "warning",
  sensitive_information: "danger",
};

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function confBar(conf) {
  const pct = Math.round(conf * 100);
  const color = conf >= 0.8 ? "success" : conf >= 0.65 ? "warning" : "danger";
  return `<div class="confbar w-100"><div style="width:${pct}%" class="bg-${color}"></div></div>
          <span class="small">${pct}%</span>`;
}

function badge(text, cls) {
  return `<span class="badge bg-${cls || "secondary"}">${esc(text)}</span>`;
}

async function getJSON(url) {
  const r = await fetch(url);
  return r.json();
}

function initStats() {
  getJSON("/api/summary").then(s => {
    const card = (title, value, cls) =>
      `<div class="col"><div class="card"><div class="card-body py-2">
         <div class="small text-secondary">${title}</div>
         <div class="h5 mb-0 text-${cls || "light"}">${value}</div>
       </div></div></div>`;
    const html = [
      card("Messages", s.total_messages),
      card("Tasks", s.tasks, "success"),
      card("Events", s.events, "primary"),
      card("Sensitive flagged", s.sensitive_messages, "danger"),
      card("Uncertain", s.uncertain_count, "warning"),
      card("Mandatory found", s.mandatory_ids_found, "info"),
    ].join("");
    document.getElementById("statCards").innerHTML = html;
  });
}

function initClassTable() {
  const table = document.getElementById("classTable").querySelector("tbody");
  const count = document.getElementById("classCount");
  const catFilter = document.getElementById("catFilter");
  const uncertainOnly = document.getElementById("uncertainOnly");
  const qFilter = document.getElementById("qFilter");

  getJSON("/api/classification").then(rows => {
    const cats = [...new Set(rows.map(r => r.category))];
    catFilter.innerHTML = `<option value="">All categories</option>` +
      cats.map(c => `<option value="${c}">${c}</option>`).join("");
  });

  async function render() {
    const params = new URLSearchParams();
    if (catFilter.value) params.set("category", catFilter.value);
    if (uncertainOnly.checked) params.set("uncertain", "1");
    if (qFilter.value.trim()) params.set("q", qFilter.value.trim());
    const rows = await getJSON("/api/classification?" + params.toString());
    table.innerHTML = rows.map(r => {
      const conf = confBar(r.confidence);
      const unc = r.uncertain ? badge("uncertain", "warning") : "";
      return `<tr>
        <td>${esc(r.message_id)} ${r.is_mandatory ? badge("demo", "info") : ""}</td>
        <td class="small">${esc(r.timestamp)}</td>
        <td class="small">${esc(r.sender)}</td>
        <td>${badge(r.category, CATEGORY_COLORS[r.category])}</td>
        <td style="min-width:120px">${conf} ${unc}</td>
        <td class="small text-secondary">${esc(r.reason)}</td>
        <td class="small"><code>${esc(r.message_masked)}</code></td>
      </tr>`;
    }).join("");
    count.textContent = `${rows.length} shown of 900`;
  }
  catFilter.onchange = render;
  uncertainOnly.onchange = render;
  qFilter.oninput = render;
  render();
}

function initItemTable() {
  const table = document.getElementById("itemTable").querySelector("tbody");
  const count = document.getElementById("itemCount");
  const typeFilter = document.getElementById("typeFilter");
  const qItems = document.getElementById("qItems");

  async function render() {
    const params = new URLSearchParams();
    if (typeFilter.value) params.set("type", typeFilter.value);
    if (qItems.value.trim()) params.set("q", qItems.value.trim());
    const rows = await getJSON("/api/items?" + params.toString());
    table.innerHTML = rows.map(r => `<tr>
      <td>${esc(r.item_id)}</td>
      <td>${badge(r.type, r.type === "task" ? "success" : "primary")}</td>
      <td>${esc(r.title)}</td>
      <td class="small">${r.deadline ? esc(r.deadline) : "&mdash;"}</td>
      <td class="small">${r.time ? esc(r.time) : "&mdash;"}</td>
      <td class="small">${r.person ? esc(r.person) : "&mdash;"}</td>
      <td>${badge(r.priority, r.priority === "high" ? "danger" :
                  r.priority === "low" ? "secondary" : "primary")}</td>
      <td class="small">${r.location ? esc(r.location) : "&mdash;"}</td>
      <td class="small">${esc(r.source_message_id)}</td>
      <td class="small text-secondary">${r.notes && r.notes.length ?
          r.notes.map(esc).join("<br>") : "&mdash;"}</td>
    </tr>`).join("");
    count.textContent = `${rows.length} items`;
  }
  typeFilter.onchange = render;
  qItems.oninput = render;
  render();
}

function initSensitiveTable() {
  const table = document.getElementById("sensTable").querySelector("tbody");
  const count = document.getElementById("sensCount");
  const riskFilter = document.getElementById("riskFilter");

  async function render() {
    const params = new URLSearchParams();
    if (riskFilter.value) params.set("risk", riskFilter.value);
    const rows = await getJSON("/api/sensitive?" + params.toString());
    table.innerHTML = rows.map(r => `<tr>
      <td>${esc(r.message_id)}</td>
      <td class="small">${esc(r.sensitivity_type).replace(/_/g, " ")}</td>
      <td>${badge(r.risk, r.risk === "high" ? "danger" : "warning")}</td>
      <td class="small"><code>${esc(r.masked_text)}</code></td>
      <td class="small">${esc(r.recommended_action).replace(/_/g, " ")}</td>
    </tr>`).join("");
    count.textContent = `${rows.length} detections (masked, no raw values served)`;
  }
  riskFilter.onchange = render;
  render();
}

initStats();
initClassTable();
initItemTable();
initSensitiveTable();