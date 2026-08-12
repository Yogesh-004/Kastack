/* Renders the 15 mandatory demo IDs with all three pipeline parts. */

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

function badge(text, cls) {
  return `<span class="badge bg-${cls || "secondary"}">${esc(text)}</span>`;
}

fetch("/api/mandatory")
  .then(r => r.json())
  .then(rows => {
    const html = rows.map(r => {
      const c = r.classification;
      const items = r.items.map(it => `<div class="small mb-1">
        ${badge(it.item_id, it.type === "task" ? "success" : "primary")}
        <strong>${esc(it.title)}</strong> &mdash; deadline
        <code>${esc(it.deadline)}</code>, time <code>${esc(it.time)}</code>,
        person ${esc(it.person) || "&mdash;"}, priority
        ${esc(it.priority)}${it.location ? `, location <code>${esc(it.location)}</code>` : ""}
        ${it.notes && it.notes.length ? `<div class="text-secondary">${it.notes.map(esc).join("; ")}</div>` : ""}
      </div>`).join("") || '<span class="small text-secondary">no extracted item</span>';
      const sens = r.sensitive.map(s => `<div class="small mb-1">
        ${badge(s.sensitivity_type.replace(/_/g, " "), s.risk === "high" ? "danger" : "warning")}
        risk ${esc(s.risk)} &mdash; action: ${esc(s.recommended_action.replace(/_/g, " "))}
        <br><code>${esc(s.masked_text)}</code></div>`).join("") ||
        '<span class="small text-secondary">no sensitive content</span>';
      return `<div class="card mb-3">
        <div class="card-header d-flex justify-content-between">
          <span>${esc(r.message_id)} <span class="text-secondary small">${esc(r.timestamp)} / ${esc(r.sender)}</span></span>
          ${badge(c.category, CATEGORY_COLORS[c.category])}
          <span class="small">confidence ${Math.round(c.confidence * 100)}% ${c.uncertain ? badge("uncertain", "warning") : ""}</span>
        </div>
        <div class="card-body">
          <div class="mb-2"><code>${esc(r.message_masked)}</code></div>
          <div class="small text-secondary mb-2">Reason: ${esc(c.reason)}</div>
          <hr class="my-2">
          <div class="small fw-bold text-info">Part 2 - extracted</div>${items}
          <hr class="my-2">
          <div class="small fw-bold text-warning">Part 3 - sensitive (masked)</div>${sens}
        </div>
      </div>`;
    }).join("");
    document.getElementById("mandatoryList").innerHTML =
      `<div class="row g-3">${html}</div>`;
  });