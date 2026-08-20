"""L2 pipeline orchestration.

Processes, in chronological order and in one living state:

    1. the original L1 corpus (900 messages)
    2. the additional L2 corpus (180 messages, MSG_0901..MSG_1080)
    3. the unseen demo batch (24 messages, DEMO_001..DEMO_024)

every message goes through the *same* code path: L1 classification +
extraction + sensitive masking, then the L2 resolution / status / priority
layer. Because the demo batch reuses the registry built from the L1+L2
corpus, a demo message such as DEMO_001 ("deadline to confirm the
interview slot ... urgent") is understood to update the *existing* task
instead of creating a new unrelated one. No results are hardcoded for any
message or query.

Raw message values never leave this machine: every stored record contains
masked text only, and the sensitive layer keeps raw secrets out of memory
on the output side.

The module exposes:

* ``L2Context``   — the living registry + message store + notices.
* ``process_batch`` — run one chronologically ordered batch through the
  whole stack and return per-batch statistics.
* ``snapshot``    — write one set of JSON deliverables for the current
  state (used for the corpus snapshot and the cumulative demo snapshot).
* ``build_documents`` / ``build_all_index`` — document store + index used
  by retrieval, the assistant and the benchmark.
"""

from __future__ import annotations

import csv
import json
import os
import re
from typing import Dict, List, Optional

from .classifier import classify
from .common import display_text, strip_openers
from .extractor import extract
from .l2_core import ItemRegistry, canonical_phrase
from .l2_groups import build_groups
from .l2_index import SparseIndex
from .l2_priority import PENDING, detect_status_action, evaluate
from .l2_routing import decide_message
from .sensitive import build_records, detect_sensitive, mask_message

MASK_LIMIT = 200


class L2Context:
    """One shared state used across batches."""

    def __init__(self):
        self.registry = ItemRegistry()
        self.meta: Dict[str, Dict] = {}        # mid -> record (masked only)
        self.message_key: Dict[str, str] = {}  # mid -> canonical key
        self.decisions: List[Dict] = []
        self.decision_by_mid: Dict[str, Dict] = {}
        self.noticeboard: List[Dict] = []
        self.sensitive_rows: List[Dict] = []
        self.routing: List[Dict] = []
        self.task_no = 0
        self.event_no = 0

    def snapshot_state(self) -> "L2Context":
        """Deep-copy the parts needed to keep a corpus snapshot stable
        while the demo batch continues to evolve the same registry."""
        clone = L2Context()
        clone.registry = self.registry
        clone.meta = dict(self.meta)
        clone.message_key = dict(self.message_key)
        clone.decisions = list(self.decisions)
        clone.decision_by_mid = dict(self.decision_by_mid)
        clone.noticeboard = list(self.noticeboard)
        clone.sensitive_rows = list(self.sensitive_rows)
        clone.routing = list(self.routing)
        clone.task_no = self.task_no
        clone.event_no = self.event_no
        return clone


def load_message_rows(path: str) -> List[Dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({
                "message_id": row["message_id"].strip(),
                "timestamp": row["timestamp"].strip(),
                "sender": row["sender"].strip(),
                "message": row["message"].strip(),
            })
    rows.sort(key=lambda r: (r["timestamp"], r["message_id"]))
    return rows


def load_queries(path: str) -> List[Dict]:
    qs = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            qs.append({"query_id": row["query_id"].strip(),
                       "query": row["query"].strip()})
    return qs


def _is_pattern_title(raw_text: str, item: Dict) -> bool:
    """True when the extractor produced a hand-tuned title rather than the
    whole-sentence fallback. Mirrors extractor.extract fallback logic so
    the L2 resolver does not rely on accidental titles."""
    body = strip_openers(raw_text)
    if item["type"] == "task":
        fallback = re.sub(r"\s+", " ", body)
        fallback = re.sub(r"^if possible[,\s]+", "", fallback,
                          flags=re.IGNORECASE)
        fallback = re.sub(r"\s*(;|by|before)\s*\d{4}-\d{2}-\d{2}.*$", "",
                          fallback).strip(" .,;")
        fallback = re.sub(r"\s+", " ", fallback)[:70].rstrip(".")
    else:
        fallback = re.sub(r"\s+", " ", body)[:70].rstrip(".")
    return item["title"].lower() != fallback.lower()


def _process_one(ctx: L2Context, row: Dict, batch: str,
                 mandatory_set: set) -> None:
    mid = row["message_id"]
    ts = row["timestamp"]
    sender = row["sender"]
    raw = row["message"]

    dets = detect_sensitive(raw)
    high_risk = any(d["risk"] == "high" for d in dets)
    secrets = [d["secret"] for d in dets]
    masked_full = mask_message(raw, secrets)
    masked = display_text(masked_full)

    # Classification, extraction and topic resolution run on the *masked*
    # text so that titles, canonical keys and group summaries can never
    # embed a raw secret (masked values are deterministic, so the same
    # secret always produces the same masked topic).
    category = classify(masked_full, sender, sensitive_detected=bool(dets))

    items = extract(mid, masked_full, sender, ts, category)
    for it in items:
        if it["type"] == "task":
            ctx.task_no += 1
            it["item_id"] = f"TASK_{ctx.task_no:03d}"
        else:
            ctx.event_no += 1
            it["item_id"] = f"EVENT_{ctx.event_no:03d}"
        it["description"] = masked

    extractor_item = items[0] if items else None
    extractor_title = extractor_item["title"] if extractor_item else None
    extractor_is_pattern = bool(items) and \
        _is_pattern_title(masked_full, extractor_item)

    status_action = detect_status_action(raw)
    resolution = ctx.registry.apply(
        mid, ts, sender, strip_openers(masked_full), category,
        extractor_title, extractor_is_pattern, extractor_item,
        status_action, raw)
    item = resolution["item"]

    decision = evaluate(item, mid, ts, sender, category, raw, status_action,
                        high_risk)
    if decision:
        ctx.decisions.append(decision)
        ctx.decision_by_mid[mid] = decision
        if item is not None:
            changed = item.priority != decision["priority"]
            item.priority = decision["priority"]
            if changed:
                item.priority_history.append({
                    "message_id": mid,
                    "timestamp": ts,
                    "priority": decision["priority"],
                    "signals": decision.get("signals", []),
                })

    key = resolution["key"] if resolution["resolved"] else None
    if key:
        ctx.message_key[mid] = key

    ctx.meta[mid] = {
        "message_id": mid,
        "timestamp": ts,
        "sender": sender,
        "category": category,
        "message_masked": masked[:MASK_LIMIT],
        "key": key,
        "item_id": item.item_id if item else None,
        "priority": decision["priority"] if decision else None,
        "status_action": status_action,
        "sensitive_types": [{"type": d["sensitivity_type"],
                             "risk": d["risk"],
                             "action": d["recommended_action"]}
                            for d in dets],
        "mandatory": mid in mandatory_set,
        "batch": batch,
    }

    # Part-3 style detections (masked only)
    ctx.sensitive_rows.extend(build_records(mid, raw))

    # Privacy route for messages that carry or hint at sensitive data.
    if dets or status_action in ("unclear",) or high_risk:
        ctx.routing.append(decide_message(mid, raw, ts, sender))

    # Noticeboard: unresolved / ambiguous / purely-notice messages.
    if not resolution["resolved"] and (
            status_action != PENDING or
            re.search(r"\b(progress|update|status|confirm|moved|deadline|"
                      r"handled|approved|sure|may be)\b", raw,
                      re.IGNORECASE)):
        ctx.noticeboard.append({
            "message_id": mid,
            "timestamp": ts,
            "sender": sender,
            "category": category,
            "kind": status_action if status_action != PENDING else "unclear",
            "note": "Could not be tied to a known task/event; treated as "
                    "an ambiguous or informational notice.",
            "message_masked": masked[:MASK_LIMIT],
        })


def process_batch(ctx: L2Context, rows: List[Dict], batch: str,
                  mandatory_set: set) -> Dict:
    for row in rows:
        _process_one(ctx, row, batch, mandatory_set)
    groups = build_groups(ctx.registry, ctx.meta, set())
    return {"batch": batch, "messages": len(rows), "groups": len(groups)}


# --------------------------------------------------------------------------
# Document store + index
# --------------------------------------------------------------------------

def build_documents(ctx: L2Context) -> List[Dict]:
    docs: List[Dict] = []
    for mid, rec in ctx.meta.items():
        docs.append({"id": mid, "kind": "message", "text": rec["message_masked"]})
    for key, item in ctx.registry.items.items():
        d = item.to_dict()
        text = " ".join(str(d.get(f, "")) for f in
                        ("title", "status", "latest_deadline"))
        docs.append({"id": item.item_id, "kind": "item", "text": text})
    return docs


def build_all_index(ctx: L2Context) -> SparseIndex:
    idx = SparseIndex(build_documents(ctx)).build()
    return idx


# --------------------------------------------------------------------------
# Snapshot + writers
# --------------------------------------------------------------------------

def _dump(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def snapshot(ctx: L2Context, out_dir: str, tag: str,
             demo_ids: set) -> Dict:
    """Write deliverables under the given tag ('l2' / 'l2_demo').

    `demo_ids` selects the batch scope: an empty set keeps everything
    (corpus snapshot), a non-empty set filters the demo batch only.
    """
    groups = build_groups(ctx.registry, ctx.meta, demo_ids)

    def keep(mid: str) -> bool:
        return (not demo_ids) or mid in demo_ids

    classification = [ctx.meta[mid] for mid in sorted(
        ctx.meta, key=lambda m: ctx.meta[m]["timestamp"]) if keep(mid)]
    decisions = [d for d in ctx.decisions if keep(d["message_id"])]
    noticeboard = [n for n in ctx.noticeboard if keep(n["message_id"])]
    routing = [r for r in ctx.routing if keep(r["request_id"])]
    sensitive_rows = [s for s in ctx.sensitive_rows if keep(s["message_id"])]

    _dump(os.path.join(out_dir, f"{tag}_items.json"),
          [ctx.registry.items[k].to_dict() for k in ctx.registry.order])
    _dump(os.path.join(out_dir, f"{tag}_priority.json"), decisions)
    _dump(os.path.join(out_dir, f"{tag}_groups.json"), groups)
    _dump(os.path.join(out_dir, f"{tag}_noticeboard.json"), noticeboard)
    _dump(os.path.join(out_dir, f"{tag}_routing.json"), routing)
    _dump(os.path.join(out_dir, f"{tag}_classification.json"), classification)
    _dump(os.path.join(out_dir, f"{tag}_sensitive.json"), sensitive_rows)

    if tag == "l2":
        _dump(os.path.join(out_dir, "l2_tasks_events.json"),
              _collect_items_output(ctx))
        _dump(os.path.join(out_dir, "l2_index_docs.json"),
              build_documents(ctx))

    return {
        "messages": len(classification),
        "items": len(ctx.registry.order),
        "groups": len(groups),
        "priority_decisions": len(decisions),
        "routing_entries": len(routing),
        "noticeboard": len(noticeboard),
    }


def _collect_items_output(ctx: L2Context) -> List[Dict]:
    # combine corpus (L1-style) extractor items generated while processing
    out = []
    for rec in sorted(ctx.meta.values(), key=lambda r: r["timestamp"]):
        if rec["item_id"]:
            out.append({
                "message_id": rec["message_id"],
                "timestamp": rec["timestamp"],
                "item_id": rec["item_id"],
                "category": rec["category"],
                "key": rec["key"],
                "priority": rec["priority"],
                "message_masked": rec["message_masked"],
            })
    return out