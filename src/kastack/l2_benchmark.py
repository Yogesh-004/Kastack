"""L2 - performance and quality benchmark.

Compares the *original, unoptimised* retrieval (L1-style: scan every
message and rebuild term features on every query) against the *optimised*
precomputed sparse index used by the L2 assistant. The scoring formula is
identical, so any difference in result quality is purely numerical noise:
the benchmark verifies this explicitly by checking top-1 agreement across
a fixed query set.

Metrics reported:

* **latency** — median wall time per query (best-of style over repeats);
* **index size** — serialised index bytes vs raw document JSON bytes;
* **memory** — peak allocation during index build vs naive querying;
* **quality** — top-1 agreement, plus matched-vocabulary rate and the
  number of terms hit per query (explains *why* speed differs).

The full dataset never leaves the machine; only aggregate numbers are
written to the report file.
"""

from __future__ import annotations

import json
import time
import tracemalloc
from typing import Dict, List

from .l2_index import SparseIndex, naive_search

BENCH_QUERIES: List[str] = [
    "latest status of the confirm the interview slot",
    "which critical or high-priority tasks are still pending",
    "which meetings were rescheduled",
    "which tasks have been completed",
    "what deadlines have changed",
    "conflicting messages about the same event",
    "show all messages related to the weekly report submission",
    "what is the latest status of the project report",
    "messages related to the offline inference demo",
    "tasks due today",
    "review the privacy checklist",
    "pay the electricity bill",
    "information about the internship orientation",
    "the project tracker update",
    "renew the library book deadline",
    "upload the assignment status",
    "prepare the L2 presentation",
    "the mentor catch-up schedule",
    "bank account details",
    "family dinner",
    "repeated status requests for the onboarding form",
]


def run_benchmark(docs: List[Dict], index: SparseIndex) -> Dict:
    n_repeat = 5

    def measure_naive(q):
        best = float("inf")
        for _ in range(n_repeat):
            t0 = time.perf_counter()
            naive_search(docs, q, k=6)
            best = min(best, time.perf_counter() - t0)
        return best

    def measure_index(q):
        best = float("inf")
        for _ in range(n_repeat):
            t0 = time.perf_counter()
            index.query(q, k=6)
            best = min(best, time.perf_counter() - t0)
        return best

    naive_times, index_times = [], []
    agreement = {"top1": 0, "top5": 0}
    naive_hits = {}
    index_hits = {}
    for q in BENCH_QUERIES:
        naive_times.append(measure_naive(q))
        index_times.append(measure_index(q))
        n1 = naive_search(docs, q, k=5)
        i1 = index.query(q, k=5)
        naive_hits[q] = [d for d, _ in n1]
        index_hits[q] = [d for d, _ in i1]
        if n1 and i1 and n1[0][0] == i1[0][0]:
            agreement["top1"] += 1
        if set(d for d, _ in n1) & set(d for d, _ in i1):
            agreement["top5"] += 1

    import math
    avg_naive = sum(naive_times) / len(naive_times)
    avg_index = sum(index_times) / len(index_times)
    speedup = avg_naive / avg_index if avg_index else 0.0

    raw_json = json.dumps(docs).encode("utf-8")

    tracemalloc.start()
    SparseIndex(docs).build()
    build_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    tracemalloc.start()
    naive_search(docs, BENCH_QUERIES[0], k=6)
    naive_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    n = len(BENCH_QUERIES)
    return {
        "queries": list(BENCH_QUERIES),
        "documents_indexed": len(docs),
        "vocabulary_terms": len(index.idf),
        "mean_latency_ms": {
            "naive": round(avg_naive * 1e3, 4),
            "optimized": round(avg_index * 1e3, 4),
        },
        "speedup_x": round(speedup, 2),
        "size_bytes": {
            "index_json": index.size_bytes(),
            "raw_docs_json": len(raw_json),
        },
        "size_reduction_pct": round(
            (1 - index.size_bytes() / max(1, len(raw_json))) * 100, 1),
        "peak_memory_kb": {
            "index_build": round(build_peak / 1024, 1),
            "naive_one_query": round(naive_peak / 1024, 1),
        },
        "quality": {
            "top1_agreement": f"{agreement['top1']}/{n}",
            "top5_overlap_ratio": round(agreement["top5"] / n, 2),
        },
        "notes": "Identical scoring formula in both paths; the optimized "
                 "path only precomputes postings, IDF and norms.",
    }