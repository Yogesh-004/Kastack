"""Flask demo application (cloud-deployable).

Serves the generated (masked) outputs through a small dashboard:
  - classification results with confidence and reasons
  - extracted tasks and events
  - sensitive-information detections (masked only, with risk + action)
  - the 15 mandatory demo IDs

No raw message text is ever served: the pipeline already masks all output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "outputs"

app = Flask(__name__)


def _load(name: str):
    with open(OUT_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def load_all():
    return {
        "classification": _load("classification.json"),
        "tasks_events": _load("tasks_events.json"),
        "sensitive": _load("sensitive_detections.json"),
        "mandatory": _load("mandatory_results.json"),
        "summary": _load("summary.json"),
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


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "messages": DATA["summary"]
                    .get("total_messages")})


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)