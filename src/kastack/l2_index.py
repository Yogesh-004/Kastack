"""L2 Part 3 - local sparse semantic index and naive baseline.

A fully local retrieval layer. There is no external embedding model: the
index is a deterministic TF-IDF sparse index over the *masked* text of
messages, extracted items, groups and priority decisions. Terms are
lowercased word tokens plus 5-character prefix stems (which give light
morphology tolerance, e.g. "checklist(s)"), and IDF weighting prefers the
distinctive subject words ("deadline", "interview", "report") over
function words.

Two retrieval paths are provided so performance can be compared fairly:

* ``naive_search``  — recomputes the whole vocabulary + features on every
  query (the "just iterate everything" approach). Deterministic and
  correct, but O(V) per query where V is the vocabulary size.
* ``SparseIndex``   — precomputes term postings, document norms and IDF
  once; a query only touches postings of its own terms (sparse dot
  product). Deterministic, much faster, uses the same scoring formula so
  results are comparable (and provably identical for the same query since
  the formula is the same).

The two paths are used by the benchmark report; the web assistant uses the
optimized index.

Irrelevant-noise guard: queries that match nothing above a small relevance
floor return no results, so the assistant can honestly report
"insufficient evidence" instead of fabricating an answer.
"""

from __future__ import annotations

import json
import math
import re
from typing import Dict, List, Optional, Tuple

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset("a an and are as at be been but by can could do does for "
                  "from had has have he her hers his how i if in into is it "
                  "its just may me more most my no not of on one or our out "
                  "s so some that the their them there these they this those "
                  "to too was we were what when where which who why will with "
                  "you your".split())
_TERM_PREFIX = 5


def tokenize(text: str) -> List[str]:
    """Return content tokens (word + light prefix stems) of a text."""
    low = text.lower()
    words = [w for w in _TOKEN_RE.findall(low) if w not in _STOP
             and len(w) >= 2]
    terms = []
    for w in words:
        terms.append(w)
        if len(w) > _TERM_PREFIX:
            terms.append(str(len(w)) + ":" + w[:_TERM_PREFIX])
    return terms


def _idf_for(df: int, n_docs: int) -> float:
    return math.log((n_docs + 1.0) / (df + 1.0)) + 1.0


class SparseIndex:
    """Precomputed TF-IDF inverted index over a document store."""

    def __init__(self, docs: Optional[List[Dict]] = None):
        self.docs: List[Dict] = docs or []           # {id, kind, text}
        self.doc_ids: List[str] = []
        self.postings: Dict[str, List[Tuple[int, float]]] = {}  # term -> [(doc_i, tf)]
        self.idf: Dict[str, float] = {}
        self.norms: List[float] = []
        self.built = False

    def build(self) -> "SparseIndex":
        n = len(self.docs)
        self.doc_ids = [d["id"] for d in self.docs]
        df: Dict[str, int] = {}
        doc_terms: Dict[int, Dict[str, int]] = {}

        for i, doc in enumerate(self.docs):
            counts: Dict[str, int] = {}
            for term in tokenize(doc["text"]):
                counts[term] = counts.get(term, 0) + 1
            doc_terms[i] = counts
            for term in counts:
                df[term] = df.get(term, 0) + 1

        idf = {t: _idf_for(v, n) for t, v in df.items()}
        postings: Dict[str, List[Tuple[int, float]]] = {}
        norms = [0.0] * n
        for i, counts in doc_terms.items():
            acc = 0.0
            for term, tf in counts.items():
                w = (1 + math.log(tf)) * idf[term]
                postings.setdefault(term, []).append((i, w))
                acc += w * w
            norms[i] = math.sqrt(acc)

        self.idf = idf
        self.postings = postings
        self.norms = norms
        self.built = True
        return self

    # -- query -----------------------------------------------------------
    def query(self, query_text: str, k: int = 8,
              floor: float = 0.02) -> List[Tuple[str, float]]:
        """Return up to `k` (doc_id, relevance) results above `floor`."""
        if not self.built:
            return []
        q_counts: Dict[str, int] = {}
        for term in tokenize(query_text):
            q_counts[term] = q_counts.get(term, 0) + 1
        scores: Dict[int, float] = {}
        q_norm = 0.0
        for term, tf in q_counts.items():
            wq = (1 + math.log(tf)) * self.idf.get(term, 0.0)
            q_norm += wq * wq
            for i, wd in self.postings.get(term, []):
                scores[i] = scores.get(i, 0.0) + wq * wd
        if q_norm == 0.0:
            return []
        qn = math.sqrt(q_norm)
        ranked = [(self.doc_ids[i], scores[i] / (qn * self.norms[i]))
                  for i in scores
                  if self.norms[i] > 0]
        # deterministic tie-break: equal relevance sorts by doc_id
        ranked.sort(key=lambda r: (r[1], r[0]), reverse=True)
        return [(doc_id, round(score, 4)) for doc_id, score in ranked
                if score >= floor][:k]

    # -- persistence ------------------------------------------------------
    def serialize(self) -> Dict:
        return {
            "doc_ids": self.doc_ids,
            "idf": self.idf,
            "postings": {t: [(i, w) for i, w in lst]
                         for t, lst in self.postings.items()},
            "norms": self.norms,
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.serialize(), fh)

    @classmethod
    def from_data(cls, data: Dict) -> "SparseIndex":
        """Rebuild a queryable index from serialized data (no docs needed)."""
        idx = cls()
        idx.doc_ids = list(data.get("doc_ids", []))
        idx.idf = dict(data.get("idf", {}))
        idx.postings = {t: [(i, w) for i, w in lst]
                        for t, lst in data.get("postings", {}).items()}
        idx.norms = list(data.get("norms", []))
        idx.built = True
        return idx

    @classmethod
    def load_meta(cls, path: str) -> Dict:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def size_bytes(self) -> int:
        return len(json.dumps(self.serialize()).encode("utf-8"))


def naive_search(docs: List[Dict], query_text: str, k: int = 8,
                 floor: float = 0.02) -> List[Tuple[str, float]]:
    """Unoptimised baseline: rebuild term features on every query.

    Same formula as SparseIndex but without any precomputed structure.
    Provided so the benchmark can demonstrate the speed/size improvement
    of the precomputed index with identical result quality.
    """
    q_terms = tokenize(query_text)
    if not q_terms:
        return []
    q_counts: Dict[str, int] = {}
    for t in q_terms:
        q_counts[t] = q_counts.get(t, 0) + 1

    n = len(docs)
    df: Dict[str, int] = {}
    doc_terms: Dict[int, Dict[str, int]] = {}
    for i, doc in enumerate(docs):
        counts: Dict[str, int] = {}
        for t in tokenize(doc["text"]):
            counts[t] = counts.get(t, 0) + 1
        doc_terms[i] = counts
        for t in counts:
            df[t] = df.get(t, 0) + 1
    idf = {t: _idf_for(v, n) for t, v in df.items()}

    results = []
    for i, doc in enumerate(docs):
        dot = 0.0
        d_norm = 0.0
        for term, tf in doc_terms[i].items():
            wd = (1 + math.log(tf)) * idf[term]
            d_norm += wd * wd
            if term in q_counts:
                wq = (1 + math.log(q_counts[term])) * idf[term]
                dot += wq * wd
        q_norm = math.sqrt(sum(
            ((1 + math.log(q_counts[t])) * idf.get(t, 0.0)) ** 2
            for t in q_counts))
        if d_norm == 0 or q_norm == 0:
            continue
        score = dot / (q_norm * math.sqrt(d_norm))
        if score >= floor:
            results.append((doc["id"], round(score, 4)))
    results.sort(key=lambda r: (r[1], r[0]), reverse=True)
    return results[:k]