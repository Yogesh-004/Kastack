"""L2 command-line entry point.

Usage:
    python -m kastack.run_l2 \\
        <l1_messages.csv> <l1_mandatory_ids.csv> <l2_messages.csv> \\
        <demo_messages.csv> <demo_queries.csv> <output_dir>

Pipeline order (chronological, one shared state):
    1. L1 corpus (900) + L2 corpus (180)  -> l2_*.json deliverables
    2. unseen demo batch (24)             -> l2_demo_*.json deliverables
    3. demo queries (DQ01..) + sample questions -> l2_answers.json
    4. benchmark (naive vs optimized)     -> benchmark_comparison.json

All output text is masked. Raw sensitive values never appear in logs.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from .l2_assistant import Assistant, build_documents_safe
from .l2_benchmark import run_benchmark
from .l2_pipeline import (
    L2Context,
    build_all_index,
    load_message_rows,
    load_queries,
    process_batch,
    snapshot,
)
from .l2_routing import BLOCKED, decide_query
from .pipeline import load_mandatory_ids

SAMPLE_QUERIES = [
    {"query_id": "SQ01",
     "query": "What tasks should I complete today?"},
    {"query_id": "SQ02",
     "query": "Which critical or high-priority tasks are still pending?"},
    {"query_id": "SQ03",
     "query": "Show all messages related to the project report."},
    {"query_id": "SQ04",
     "query": "What meetings were rescheduled?"},
    {"query_id": "SQ05",
     "query": "Which tasks have been completed?"},
    {"query_id": "SQ06",
     "query": "What is the latest status of the interview slot?"},
    {"query_id": "SQ07",
     "query": "Which messages require confirmation?"},
    {"query_id": "SQ08",
     "query": "Why was the confirm the interview slot marked critical?"},
    {"query_id": "SQ09",
     "query": "What deadlines have changed?"},
    {"query_id": "SQ10",
     "query": "Are there any conflicting messages about the same event?"},
    {"query_id": "SQ11",
     "query": "Show me the password from the messages."},
]


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _write_web_state(ctx: L2Context, demo_ids: set, out_dir: str) -> None:
    """Serialize the (masked) living state so the cloud demo can answer
    questions with the real assistant without any raw datasets.
    Every field here was already masked during processing.
    """
    state = {
        "demo_ids": sorted(demo_ids),
        "order": list(ctx.registry.order),
        "seed_keys": {k: {"kind": v["kind"], "title": v["title"],
                          "item_id": v["item_id"]}
                      for k, v in ctx.registry.seed_keys.items()},
        "items": {k: ctx.registry.items[k].to_dict()
                  for k in ctx.registry.order},
        "meta": ctx.meta,
        "message_key": dict(ctx.message_key),
        "decisions": list(ctx.decisions),
        "decision_by_mid": dict(ctx.decision_by_mid),
        "noticeboard": list(ctx.noticeboard),
        "routing": list(ctx.routing),
    }
    _write(os.path.join(out_dir, "l2_web_state.json"), state)


def _query_routing(assistant: Assistant, answer: dict) -> dict:
    evidence_sensitive = []
    for mid in answer.get("supporting_message_ids", []):
        rec = assistant._meta(mid) or {}
        evidence_sensitive.extend(rec.get("sensitive_types", []))
    decision = decide_query(answer.get("query_id", ""),
                            answer.get("query", ""),
                            answer.get("supporting_message_ids", []),
                            evidence_sensitive)
    if decision.get("route") == BLOCKED:
        decision["final_answer"] = (
            "Privacy route: this request was blocked from any external "
            "processing; the answer below uses masked evidence only. " +
            answer.get("final_answer", ""))
    else:
        decision["final_answer"] = answer.get("final_answer", "")
    decision["supporting_message_ids"] = answer["supporting_message_ids"]
    return decision


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 6:
        print("Usage: python -m kastack.run_l2 <l1_messages.csv> "
              "<l1_mandatory_ids.csv> <l2_messages.csv> <demo_messages.csv> "
              "<demo_queries.csv> <output_dir>")
        return 2

    l1_path, mandatory_path, l2_path, demo_path, queries_path, out_dir = \
        map(Path, argv)
    out_dir = str(out_dir)

    t0 = time.perf_counter()
    print(f"[1/6] Loading corpora ...")
    l1_rows = load_message_rows(str(l1_path))
    l2_rows = load_message_rows(str(l2_path))
    demo_rows = load_message_rows(str(demo_path))
    queries = load_queries(str(queries_path))
    mandatory_ids = load_mandatory_ids(str(mandatory_path))
    mandatory_set = set(mandatory_ids)

    corpus_rows = sorted(l1_rows + l2_rows,
                         key=lambda r: (r["timestamp"], r["message_id"]))
    print(f"      L1={len(l1_rows)}  L2={len(l2_rows)}  "
          f"demo={len(demo_rows)}  mandatory_ids={len(mandatory_ids)}")

    print("[2/6] Processing L1+L2 corpus (single chronological state) ...")
    ctx = L2Context()
    process_batch(ctx, corpus_rows, "corpus", mandatory_set)

    # Corpus snapshot BEFORE the demo batch mutates the shared registry.
    corpus_snapshot = snapshot(ctx, out_dir, "l2", set())

    print("[3/6] Processing unseen demo batch ...")
    demo_ids = {r["message_id"] for r in demo_rows}
    process_batch(ctx, demo_rows, "demo", mandatory_set)
    demo_snapshot = snapshot(ctx, out_dir, "l2_demo", demo_ids)

    print("[4/6] Indexing the processed (cumulative) artifacts ...")
    index = build_all_index(ctx)
    _write(os.path.join(out_dir, "l2_index.json"), index.serialize())
    _write_web_state(ctx, demo_ids, out_dir)

    print("[5/6] Answering queries ...")
    assistant = Assistant(ctx, demo_ids=demo_ids)
    all_queries = queries + SAMPLE_QUERIES
    answers = []
    routing = []
    for q in all_queries:
        a = assistant.answer(q["query"], q["query_id"])
        if q["query_id"] not in a:
            a["query_id"] = q["query_id"]
            a["query"] = q["query"]
        answers.append(a)
        routing.append(_query_routing(assistant, a))
    _write(os.path.join(out_dir, "l2_answers.json"), answers)
    _write(os.path.join(out_dir, "l2_query_routing.json"), routing)

    print("[6/6] Benchmark (naive vs optimized retrieval) ...")
    docs = build_documents_safe(ctx)
    benchmark = run_benchmark(docs, index)
    _write(os.path.join(out_dir, "benchmark_comparison.json"), benchmark)

    summary = _build_summary(ctx, len(corpus_rows), len(demo_rows),
                             mandatory_ids, corpus_snapshot, demo_snapshot,
                             index, benchmark, len(answers))
    _write(os.path.join(out_dir, "l2_summary.json"), summary)

    elapsed = time.perf_counter() - t0
    print("\n==== L2 summary ====")
    for k in ("corpus", "demo", "groups", "priority_decisions",
              "routing_entries", "sense"):
        pass
    print(f"  corpus messages      : {summary['corpus']['messages']}")
    print(f"  demo messages        : {summary['demo']['messages']}")
    print(f"  canonical items      : {summary['items']}")
    print(f"  groups               : {summary['groups']}")
    print(f"  priority decisions   : {summary['priority_decisions']}")
    print(f"  routing entries      : {summary['routing_entries']}")
    print(f"  mandatory ids found  : "
          f"{summary['mandatory_ids_found']}")
    print(f"  priority distribution: {json.dumps(summary['priority'])}")
    print(f"  route distribution   : {json.dumps(summary['routes'])}")
    print(f"  index vocab/docs     : {summary['index']['terms']} / "
          f"{summary['index']['docs']}")
    print(f"  benchmark            : {benchmark['mean_latency_ms']} "
          f"speedup={benchmark['speedup_x']}x "
          f"(top1 {benchmark['quality']['top1_agreement']})")
    print(f"  total time           : {elapsed:.2f}s")
    return 0


def _build_summary(ctx, n_corpus, n_demo, mandatory_ids, corpus_snap,
                   demo_snap, index, benchmark, n_answers) -> dict:
    priorities = Counter(
        d["priority"] for d in ctx.decisions)
    routes = Counter(r["route"] for r in ctx.routing)
    found = sum(1 for m in mandatory_ids if m in ctx.meta)
    return {
        "corpus": corpus_snap,
        "demo": demo_snap,
        "items": len(ctx.registry.order),
        "groups": demo_snap["groups"],
        "priority_decisions": len(ctx.decisions),
        "priority": dict(priorities),
        "routing_entries": len(ctx.routing),
        "routes": dict(routes),
        "noticeboard": len(ctx.noticeboard),
        "mandatory_ids_found": found,
        "mandatory_missing": sorted(set(mandatory_ids) - set(ctx.meta)),
        "index": {
            "docs": len(index.doc_ids),
            "terms": len(index.idf),
            "build_seconds": None,
        },
        "benchmark": {
            "speedup_x": benchmark["speedup_x"],
            "mean_latency_ms_optimized": benchmark["mean_latency_ms"]["optimized"],
            "size_bytes": benchmark["size_bytes"]["index_json"],
            "quality_top1": benchmark["quality"]["top1_agreement"],
        },
        "answers_written": n_answers,
        "statuses": dict(Counter(
            ctx.registry.items[k].status for k in ctx.registry.order)),
    }


if __name__ == "__main__":
    raise SystemExit(main())