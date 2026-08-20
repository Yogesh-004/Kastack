# Kastack — Deliverables

## L1 (base assignment)

| Deliverable | Location |
|-------------|----------|
| Classification (900 rows, 6 categories, confidence + reason) | `outputs/classification.json` |
| Tasks & events extraction | `outputs/tasks_events.json` |
| Sensitive-information detection (type, risk, masked text, action) | `outputs/sensitive_detections.json` |
| Mandatory 15 IDs, all three parts | `outputs/mandatory_results.json` |
| Aggregate summary | `outputs/summary.json` |
| Tests (32) | `tests/` |
| Web demo (masked-only) | `web/` + `/l2` |
| Demonstration video | `VIDEO_SCRIPT.md` (L1) / `VIDEO_SCRIPT_L2.md` (L2) |

## L2 extension (current assignment)

| Deliverable | Location |
|-------------|----------|
| Priority engine decisions (per message, full history, reasons + signals + confidence) | `outputs/l2_priority.json`, `outputs/l2_demo_priority.json` |
| Related-message grouping (threads, summaries, conflicts) | `outputs/l2_groups.json`, `outputs/l2_demo_groups.json` |
| Semantic search index (local, deterministic TF-IDF) | `outputs/l2_index.json`, `outputs/l2_index_docs.json` |
| Intelligent assistant answers (DQ01–DQ09 + corpus queries) | `outputs/l2_answers.json`, `outputs/l2_query_routing.json` |
| Privacy-aware routing (blocked / ask-for-confirmation / process-locally) | `outputs/l2_routing.json`, `outputs/l2_demo_routing.json` |
| Benchmark: naive-search vs sparse index (same TF-IDF formula) | `outputs/benchmark_comparison.json` |
| Masked living state for the cloud assistant | `outputs/l2_web_state.json` |
| L2 documentation (architecture, scoring, routing policy, benchmark, AI declaration) | `README.md` |
| Tests (28 L2 + 32 L1) | `tests/test_l2.py` |
| Demo video with demo CSV + queries | `VIDEO_SCRIPT_L2.md` |

### Benchmark summary (latest run)

| Metric | Value |
|--------|-------|
| Messages processed | 1080 corpus + 24 demo |
| Canonical items / groups | 52 / 52 |
| Priority decisions | 523 |
| Routing entries | 135 (75 blocked, 35 ask, 25 local) |
| Demo-batch routes | 8 (3 blocked, 4 ask, 1 local) |
| Mandatory IDs found | 15 / 15 |
| Index | 1156 docs, 738 terms |
| Speedup vs naive baseline | ~246x |
| Top-1 quality (naive == index) | 21 / 21 |
| Total run time | ~1.9 s |

### Live demo

- L2 assistant (live, deterministic, masked state only) and dashboards:
  `/l2` page of the Flask app (see `web/`).
- Cloud deployment: `vercel.json` (functions bundle `outputs/**`, `web/**`,
  `src/**`; datasets are git-ignored and never deployed).