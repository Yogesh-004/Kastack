"""Flask demo application (cloud-deployable).

Serves the generated (masked) outputs through a small dashboard:
  - classification results with confidence and reasons
  - extracted tasks and events
  - sensitive-information detections (masked only, with risk + action)
  - the 15 mandatory demo IDs
  - the L2 extension: priority, groups, privacy routing, the intelligent
    assistant (live, deterministic, over the masked state only) and the
    benchmark comparison

No raw message text is ever served: the pipeline already masks all output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent.parent

# The kastack package lives under ./src and is bundled (not pip-installed) on
# the serverless runtime, so make it importable regardless of how the app is
# launched. Without this, /api/l2/ask raises ModuleNotFoundError on Vercel.
for _p in (BASE_DIR / "src", BASE_DIR / "web"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

# Robust output lookup: works from a normal checkout and from a bundled
# serverless runtime where the working directory may differ.
_OUTPUT_CANDIDATES = [
    BASE_DIR / "outputs",
    Path.cwd() / "outputs",
    Path.cwd().parent / "outputs",
]
OUT_DIR = next((p for p in _OUTPUT_CANDIDATES if (p / "summary.json").exists()),
               BASE_DIR / "outputs")

app = Flask(__name__)


def _load(name: str):
    with open(OUT_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def _load_optional(name: str, default=None):
    path = OUT_DIR / name
    if not path.exists():
        return default
    return _load(name)


def load_all():
    return {
        "classification": _load("classification.json"),
        "tasks_events": _load("tasks_events.json"),
        "sensitive": _load("sensitive_detections.json"),
        "mandatory": _load("mandatory_results.json"),
        "summary": _load("summary.json"),
        "l2_summary": _load_optional("l2_summary.json", {}),
        "l2_items": _load_optional("l2_items.json", []),
        "l2_groups": _load_optional("l2_groups.json", []),
        "l2_priority": _load_optional("l2_priority.json", []),
        "l2_routing": _load_optional("l2_routing.json", []),
        "l2_noticeboard": _load_optional("l2_noticeboard.json", []),
        "l2_answers": _load_optional("l2_answers.json", []),
        "l2_query_routing": _load_optional("l2_query_routing.json", []),
        "l2_demo_groups": _load_optional("l2_demo_groups.json", []),
        "l2_demo_priority": _load_optional("l2_demo_priority.json", []),
        "l2_demo_routing": _load_optional("l2_demo_routing.json", []),
        "l2_demo_classification": _load_optional(
            "l2_demo_classification.json", []),
        "l2_demo_items": _load_optional("l2_demo_items.json", []),
        "l2_demo_noticeboard": _load_optional("l2_demo_noticeboard.json", []),
        "l2_index_docs": _load_optional("l2_index_docs.json", []),
        "l2_web_state": _load_optional("l2_web_state.json", None),
        "benchmark": _load_optional("benchmark_comparison.json", None),
    }


DATA = load_all()

CATEGORY_LABELS = {
    "action_required": "Action Required",
    "meeting_or_event": "Meeting or Event",
    "personal_information": "Personal Information",
    "general_information": "General Information",
    "promotional": "Promotional",
    "sensitive_information": "Sensitive Information",
}
RISK_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}

ROUTE_LABELS = {
    "blocked": ("Blocked", "danger"),
    "ask_for_confirmation": ("Ask for confirmation", "warning"),
    "process_locally": ("Process locally", "success"),
}
PRIORITY_LABELS = {
    "critical": ("critical", "danger"),
    "high": ("high", "warning"),
    "medium": ("medium", "primary"),
    "low": ("low", "secondary"),
}

_L2_ASSISTANT = None


def _get_assistant():
    """Build the live (deterministic) assistant once, off the masked state."""
    global _L2_ASSISTANT
    if _L2_ASSISTANT is not None:
        return _L2_ASSISTANT
    if not DATA.get("l2_web_state"):
        return None
    try:
        from l2_state import build_web_context, build_web_index
    except ImportError:  # launched from repo root (flask --app web.app)
        from web.l2_state import build_web_context, build_web_index
    from kastack.l2_assistant import Assistant
    ctx, demo_ids = build_web_context(DATA["l2_web_state"])
    build_web_index(ctx)
    assistant = Assistant(ctx, demo_ids=demo_ids)
    _L2_ASSISTANT = (assistant, demo_ids)
    return _L2_ASSISTANT


@app.route("/")
def index():
    return render_template(
        "index.html",
        categories=CATEGORY_LABELS,
        risk_labels=RISK_LABELS,
    )


@app.route("/mandatory")
def mandatory():
    return render_template("mandatory.html", categories=CATEGORY_LABELS)


@app.route("/l2")
def l2():
    return render_template(
        "l2.html",
        route_labels=ROUTE_LABELS,
        priority_labels=PRIORITY_LABELS,
        l2_available=bool(DATA.get("l2_summary")),
        live_assistant=bool(DATA.get("l2_web_state")),
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "messages": DATA["summary"]
                    .get("total_messages")})


@app.route("/health")
def health():
    """Human-readable status page (the nav 'Health' link lands here)."""
    l2 = bool(DATA.get("l2_summary"))
    live = bool(DATA.get("l2_web_state"))
    return render_template(
        "health.html",
        status="ok",
        messages=DATA["summary"].get("total_messages"),
        l2_available=l2,
        live_assistant=live,
    )


@app.route("/api/summary")
def api_summary():
    return jsonify(DATA["summary"])


@app.route("/api/classification")
def api_classification():
    category = request.args.get("category", "").strip()
    query = request.args.get("q", "").strip().lower()
    only_uncertain = request.args.get("uncertain") == "1"
    rows = DATA["classification"]
    if category:
        rows = [r for r in rows if r["category"] == category]
    if only_uncertain:
        rows = [r for r in rows if r["uncertain"]]
    if query:
        rows = [r for r in rows
                if query in r["message_id"].lower()
                or query in r["sender"].lower()
                or query in r["message_masked"].lower()]
    return jsonify(rows)


@app.route("/api/items")
def api_items():
    item_type = request.args.get("type", "").strip()
    query = request.args.get("q", "").strip().lower()
    rows = DATA["tasks_events"]
    if item_type:
        rows = [r for r in rows if r["type"] == item_type]
    if query:
        rows = [r for r in rows
                if query in r["title"].lower()
                or query in r["source_message_id"].lower()
                or query in r["item_id"].lower()]
    return jsonify(rows)


@app.route("/api/sensitive")
def api_sensitive():
    risk = request.args.get("risk", "").strip()
    rows = DATA["sensitive"]
    if risk:
        rows = [r for r in rows if r["risk"] == risk]
    return jsonify(rows)


@app.route("/api/mandatory")
def api_mandatory():
    return jsonify(DATA["mandatory"])


# --------------------------------------------------------------------------
# L2 sections
# --------------------------------------------------------------------------

def _filter_rows(rows, key, aliases=()):
    q = request.args.get("q", "").strip().lower()
    if not q:
        return rows
    names = (key,) + tuple(aliases)
    return [r for r in rows
            if any(q in str(r.get(n, "")).lower() for n in names)]


@app.route("/api/l2/items")
def api_l2_items():
    rows = DATA.get("l2_items") or []
    extra = DATA.get("l2_demo_items") or []
    merged = {r["item_id"]: r for r in rows + extra}
    return jsonify(_filter_rows(list(merged.values()), "title",
                                ("key", "item_id")))


@app.route("/api/l2/groups")
def api_l2_groups():
    rows = DATA.get("l2_groups") or []
    extra = DATA.get("l2_demo_groups") or []
    merged = {r.get("group_id", r.get("item_id")): r for r in rows + extra}
    return jsonify(_filter_rows(list(merged.values()), "title",
                                ("canonical_key", "group_id")))


@app.route("/api/l2/priority")
def api_l2_priority():
    rows = DATA.get("l2_priority") or []
    return jsonify(_filter_rows(rows, "item_id", ("message_id",)))


@app.route("/api/l2/noticeboard")
def api_l2_noticeboard():
    rows = DATA.get("l2_noticeboard") or []
    return jsonify(_filter_rows(rows, "message_id"))


@app.route("/api/l2/routing")
def api_l2_routing():
    scope = request.args.get("scope", "corpus").strip()
    route = request.args.get("route", "").strip()
    rows = []
    if scope == "demo":
        rows = DATA.get("l2_demo_routing") or []
    else:
        rows = DATA.get("l2_routing") or []
    if route:
        rows = [r for r in rows if r.get("route") == route]
    return jsonify(rows)


@app.route("/api/l2/answers")
def api_l2_answers():
    return jsonify({
        "answers": DATA.get("l2_answers") or [],
        "query_routing": DATA.get("l2_query_routing") or [],
    })


@app.route("/api/l2/demo")
def api_l2_demo():
    return jsonify({
        "classification": DATA.get("l2_demo_classification") or [],
        "items": DATA.get("l2_demo_items") or [],
        "priority": DATA.get("l2_demo_priority") or [],
        "routing": DATA.get("l2_demo_routing") or [],
        "groups": DATA.get("l2_demo_groups") or [],
        "noticeboard": DATA.get("l2_demo_noticeboard") or [],
    })


@app.route("/api/l2/benchmark")
def api_l2_benchmark():
    return jsonify({
        "benchmark": DATA.get("benchmark"),
        "summary": DATA.get("l2_summary"),
        "index_docs": DATA.get("l2_index_docs"),
    })


@app.route("/api/l2/ask")
def api_l2_ask():
    """Live deterministic assistant over the masked state (no external AI,
    no raw data). The same intent + evidence-guard pipeline as locally."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "missing q"}), 400
    built = _get_assistant()
    if built is None:
        return jsonify({
            "error": "l2_web_state.json is not available on this instance; "
                     "the precomputed answers tab still works.",
        }), 503
    assistant, demo_ids = built
    answer = assistant.answer(q, "WEB")
    from kastack.l2_routing import BLOCKED, decide_query
    evidence_sensitive = []
    for mid in answer.get("supporting_message_ids", []):
        rec = assistant._meta(mid) or {}
        evidence_sensitive.extend(rec.get("sensitive_types", []))
    routing = decide_query("WEB", q, answer.get("supporting_message_ids", []),
                           evidence_sensitive)
    if routing.get("route") == BLOCKED:
        routing["final_answer"] = (
            "Privacy route: this request was blocked from any external "
            "processing; the answer below uses masked evidence only. " +
            answer.get("final_answer", ""))
    else:
        routing["final_answer"] = answer.get("final_answer", "")
    return jsonify({
        "answer": answer,
        "routing": routing,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)