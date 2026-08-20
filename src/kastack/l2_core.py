"""L2 core: canonical topic resolution + living item/thread state machine.

This module sits *above* the L1 pipeline. L1 extracts one item per
actionable message, which means the same real-world subject ("review the
privacy checklist") is spread over many message-level items. L2 merges
those message-level items into one *canonical item* per subject and keeps
a living state for it: status, deadline history, schedule history,
conflicts, follow-up count and the message thread that refers to it.

Two layers of resolution are used:

1. If the L1 extractor produced a *pattern-based* title for a message
   (not a whole-sentence fallback), the title is canonicalised and used.
   This covers all L1-style request/event messages with high confidence.
2. Otherwise, explicit reference patterns are matched against the message
   body ("Following up on X", "Update: X has been completed", "The
   deadline to X is now ...", "The X has been moved to ..."). Patterns are
   ordered: specific forms are tried before generic ones.

Canonical matching is meaning-based, not single-keyword based: canonical
phrases are compared with (a) exact match, (b) token Jaccard similarity,
(c) a containment rule (a short mention such as "the model results" is
folded into "review the model results"). Ties and low-margin matches are
kept deliberately separate and marked `unclear` instead of guessing.

Nothing in this module invents data: a relative deadline stays unresolved
and is recorded with a note; an ambiguous mention becomes a latent group
with status "unclear".
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .common import clean_text, find_iso_date, find_time, first_upper

ISO_DATE = r"\d{4}-\d{2}-\d{2}"

# Statuses used across the L2 outputs.
PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
CANCELLED = "cancelled"
RESCHEDULED = "rescheduled"
UNCLEAR = "unclear"

# Message-prefix fillers that carry no topic information of their own.
_PREFIX_RE = re.compile(
    r"^\s*("
    r"follow-up\s*:\s*|follow up\s*:\s*|additional update\s*:\s*|"
    r"update\s*:\s*|reminder\s*:\s*|quick update\s*:\s*|just checking[—-]\s*|"
    r"for today\s*:\s*|can you help\??\s*|please note\s*:\s*|fyi\s*:\s*|"
    r"important\s*:\s*|one more thing\s*:\s*|hi,?\s*"
    r")+",
    re.IGNORECASE,
)

# Words dropped when comparing canonical phrases (function words).
_DROP = {
    "a", "an", "the", "and", "or", "for", "of", "on", "at", "in", "to",
    "by", "before", "with", "is", "are", "was", "been", "being", "have",
    "has", "had", "it", "its", "this", "that", "be", "your", "our", "my",
    "please", "new", "next", "we", "i", "you", "already", "now", "still",
}

# (status_action, regex) — statuses a message imposes on the item it refers
# to. The canonical pattern set lives in l2_priority.detect_status_action
# (specific-before-generic ordering matters, so one ordering is shared).

# Topic reference patterns, most specific first. Each entry is
# (label, regex, capture_group, kind_hint). `kind_hint` in {"task",
# "event", None} narrows canonical matching.
REF_PATTERNS: List[Tuple[str, str, int, Optional[str]]] = [
    # --- dedicated L2/L demo forms -------------------------------------
    ("completed", r"update\s*:\s*(.+?)\s+has\s+been\s+completed\s+successfully", 1, "task"),
    ("completed", r"confirmed\s*:\s*(.+?)\s+has\s+been\s+completed\b[^.]*", 1, "task"),
    ("cancelled", r"you\s+can\s+cancel\s+(.+?)\s*;", 1, "task"),
    ("cancelled", r"you\s+can\s+cancel\s+(.+?)[.!?]*$", 1, "task"),
    ("cancelled", r"cancel\s+(.+?)\s*;", 1, "task"),
    ("deadline_to", r"the\s+deadline\s+to\s+(.+?)\s+is\s+now\b", 1, "task"),
    ("deadline_for", r"the\s+deadline\s+for\s+(.+?)\s+has\s+been\s+extended\s+to\b", 1, "task"),
    ("due_note", r"please\s+note\s+that\s+(.+?)\s+is\s+due\s+on\s+" + ISO_DATE, 1, "task"),
    ("latest_instruction", r"the\s+latest\s+instruction\s+says\s+(.+?)\s+is\s+due\s+on\s+" + ISO_DATE, 1, "task"),
    ("deadline_conflict", r"one\s+message\s+says\s+[^,]+,\s*but\s+the\s+latest\s+instruction\s+says\s+(.+?)\s+is\s+due\s+on\s+" + ISO_DATE, 1, "task"),
    ("followup_on", r"following\s+up\s+on\s+(.+?)\s*;", 1, None),
    ("share_update", r"share\s+an\s+update\s+on\s+(.+?)[?.]*$", 1, None),
    ("any_update", r"any\s+update\s+on\s+(.+?)[?.]*$", 1, None),
    ("started", r"confirm\s+whether\s+you\s+started\s+(?:to\s+)?(.+?)[?.]*$", 1, "task"),
    ("progress_item", r"any\s+progress\s+on\s+the\s+item\s+concerning\s+(.+?)[?.]*$", 1, None),
    ("progress", r"any\s+progress\s+on\s+(.+?)[?.]*$", 1, None),
    ("check_status", r"check\s+the\s+latest\s+status\s+of\s+(.+?)[?.]*$", 1, None),
    ("still_needs", r"the\s+work\s+we\s+discussed\s+about\s+(.+?)\s+still\s+needs\s+attention", 1, None),
    ("handled", r"has\s+the\s+(?:the\s+)?(.+?)\s+item\s+been\s+handled\s+yet[?]?", 1, None),
    ("earlier_request", r"earlier\s+request\s+about\s+(.+?)[?.]*$", 1, None),
    ("status_request", r"status\s+request\s+about\s+(.+?)[,.]", 1, None),
    ("new_task", r"new\s+task\s*:\s*(.+?)(?:\s+by\s+" + ISO_DATE + r")?[.!?]*$", 1, "task"),
    ("new_task2", r"new\s+task\s*:\s*(.+?)$", 1, "task"),
    ("new_session", r"a\s+new\s+(.+?)\s+(?:session|meeting)\s+is\s+scheduled\s+for\s+" + ISO_DATE, 1, "event"),
    ("moved", r"the\s+(.+?)\s+has\s+(?:been\s+)?moved\s+to\s+" + ISO_DATE, 1, "event"),
    ("moved2", r"the\s+(.+?)\s+has\s+(?:been\s+)?moved\s+to\b", 1, "event"),
    ("cancelled_event", r"the\s+(.+?)\s+has\s+been\s+cancelled", 1, "event"),
    ("date_for", r"the\s+date\s+for\s+(.+?)\s+stays\s+the\s+same", 1, "event"),
    ("may_move", r"may\s+move\s+(?:the\s+)?(.+?)\s*;", 1, "event"),
    ("could_be_done", r"(.+?)\s+might\s+already\s+be\s+(?:done|finished|completed)", 1, None),
    ("reminder_item", r"reminder\s*:\s*(?:the\s+)?(.+?)\s+(?:happens\s+on|is\s+on|at\b)", 1, "event"),
    # --- L1-style request forms -----------------------------------------
    ("need_by", r"i\s+need\s+you\s+to\s+(.+?)\s+(?:by|before)\s+" + ISO_DATE, 1, "task"),
    ("need", r"i\s+need\s+you\s+to\s+(.+?)$", 1, "task"),
    ("can_by", r"(?:can\s+you|could\s+you)\s+(.+?)\s+(?:by|before)\s+" + ISO_DATE, 1, "task"),
    ("can", r"(?:can\s+you|could\s+you)\s+(.+?)[?.]*$", 1, None),
    ("please_by", r"please\s+(.+?)\s+(?:by|before)\s+" + ISO_DATE, 1, "task"),
    ("please", r"please\s+(.+?)[?.]*$", 1, None),
    ("due_on", r"(.+?)\s+is\s+due\s+on\s+" + ISO_DATE, 1, "task"),
    ("dont_forget", r"don'?t\s+forget\s+to\s+(.+?)\s*;", 1, "task"),
    ("deadline_is", r"(.+?)\s*;\s*deadline\s+is\s+" + ISO_DATE, 1, "task"),
    ("schedule_for", r"(.+?)\s+is\s+scheduled\s+for\s+" + ISO_DATE, 1, "event"),
    ("schedule", r"(.+?)\s+is\s+scheduled\s+for\b", 1, "event"),
    ("calendar_update", r"calendar\s+update\s*:\s*(.+?)(?:[,;]|$)", 1, "event"),
    ("joins", r"please\s+join\s+(?:the\s+)?(.+?)\s+(?:on\b|,|$)", 1, "event"),
    ("available_for", r"are\s+you\s+available\s+for\s+(.+?)(?:\s+at\b|\?|$)", 1, "event"),
    ("happens_on", r"(.+?)\s+(?:happens\s+on|is\s+on)\s+", 1, "event"),
    # --- generic status-question form (latent topics) -------------------
    ("status_question", r"^(?:was|is|did|have|are|were)\s+(?:the\s+)?"
                        r"(.+?)\s+(?:been\s+)?"
                        r"(?:approved|done|completed|handled|sent|submitted|"
                        r"updated|reviewed|moved|merged|verified|shared|"
                        r"cancelled|canceled)\b(?:\s+by\s+[^?.]+)?[?.]*$",
     1, None),
]

# Accidentally captured trailing filler to drop from topic phrases.
_TAIL_CLEAN = re.compile(
    r"\s*(?:;\s*it\s+is\s+no\s+longer\s+(?:required|needed)"
    r"|\s*,\s*earlier\s+than\s+previously\s+planned"
    r"|\s*,\s*although\s+the\s+earlier\s+message\s+listed\s+another\s+date"
    r"|\s*is\s+it\s+in\s+progress\??"
    r"|\s*still\s+needs\s+attention)"
)


def strip_prefixes(text: str) -> str:
    """Remove stacked policy-neutral prefixes from a raw message."""
    prev = None
    current = text
    while current != prev:
        prev = current
        current = _PREFIX_RE.sub("", current, count=1).strip()
    return current


def topic_tokens(phrase: str) -> List[str]:
    """Content tokens of a canonical phrase (lowercased, stopwords removed)."""
    low = clean_text(phrase)
    low = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", low)
    low = re.sub(r"\b\d{1,2}[:.]\d{2}\b", " ", low)
    low = low.replace("-", " ")
    tokens = [t for t in re.split(r"[^a-z0-9]+", low) if t and t not in _DROP]
    return tokens


def canonical_phrase(phrase: str) -> str:
    """Normalise a raw topic capture into a canonical key string."""
    low = clean_text(phrase)
    low = re.sub(r"\b\('tentative'\)|\(tentative\)", "", low)
    low = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", low)
    low = re.sub(r"\b\d{1,2}[:.]\d{2}\b", " ", low)
    low = re.sub(r"\b(at|on)\s+(tomorrow|today|tonight)\b", "", low)
    low = re.sub(r"\b(?:tomorrow|today|tonight)\b", " ", low)
    low = re.sub(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", " ", low)
    low = re.sub(r"\b(?:am|pm)\b", " ", low)
    low = re.sub(r"\b(?:session|meeting)\b", " ", low)
    low = _TAIL_CLEAN.sub("", low)
    low = re.sub(r"\b(new\s+task|the\s+deadline\s+to|please\s+note\s+that)\b", "", low)
    low = re.sub(r"^[\s\-_]+|[\s\-_]+$", "", low)
    low = re.sub(r"\s+", " ", low).strip(" .,;:!?-")
    return low


def canonical_quality(phrase: str) -> float:
    """Confidence that the captured phrase really names a topic."""
    tokens = topic_tokens(phrase)
    if len(tokens) >= 2:
        return 0.85
    if len(tokens) == 1:
        return 0.55
    return 0.30


class ItemRecord:
    """Living state of one canonical task or event."""

    def __init__(self, key: str, kind: str, title: str, message_id: str,
                 timestamp: str):
        self.key = key
        self.item_id = ""                       # assigned on registration
        self.kind = kind                        # task | event | task/event
        self.title = title                      # first (display) title
        self.status = PENDING
        self.status_history: List[Dict] = []
        self.latest_deadline: Optional[str] = None
        self.deadline_history: List[Dict] = []
        self.latest_time: Optional[str] = None
        self.latest_location: Optional[str] = None
        self.person: Optional[str] = None
        self.priority: Optional[str] = None
        self.priority_history: List[Dict] = []
        self.message_ids: List[str] = [message_id]
        self.related_item_ids: List[str] = []
        self.source_message_id = message_id
        self.followup_count = 0
        self.notes: List[str] = []
        self.conflicts: List[Dict] = []
        self.sensitive_flag = False
        self.resolution_confidence = 0.9
        self.created_at = timestamp
        self.last_update = timestamp

    def to_dict(self) -> Dict:
        return {
            "item_id": self.item_id,
            "type": self.kind,
            "key": self.key,
            "title": first_upper(self.title),
            "status": self.status,
            "status_history": self.status_history,
            "latest_deadline": self.latest_deadline,
            "deadline_history": self.deadline_history,
            "latest_time": self.latest_time,
            "latest_location": self.latest_location,
            "person": self.person,
            "priority": self.priority,
            "priority_history": self.priority_history,
            "message_ids": list(self.message_ids),
            "related_item_ids": list(self.related_item_ids),
            "source_message_id": self.source_message_id,
            "followup_count": self.followup_count,
            "notes": list(self.notes),
            "conflicts": list(self.conflicts),
            "sensitive_flag": self.sensitive_flag,
            "resolution_confidence": round(self.resolution_confidence, 3),
            "created_at": self.created_at,
            "last_update": self.last_update,
        }


class ItemRegistry:
    """Holds every canonical item and resolves messages to items."""

    def __init__(self):
        self.items: Dict[str, ItemRecord] = {}
        self.seed_keys: Dict[str, Dict] = {}    # key -> {kind, title, id,...}
        self.order: List[str] = []
        self.next_task_no = 1
        self.next_event_no = 1

    # -- seeding ---------------------------------------------------------
    def seed(self, key: str, kind: str, title: str, item_id: str) -> None:
        """Pre-register a known topic (from L1 extracted items)."""
        existing = self.seed_keys.get(key)
        if existing is None:
            self.seed_keys[key] = {"kind": kind, "title": title,
                                   "item_id": item_id}
            return
        if "task" in existing["kind"] and "event" in kind:
            existing["kind"] = "task/event"

    def _claim_id(self, kind: str) -> str:
        if kind == "event":
            self.next_event_no += 1
            return f"EVENT_{self.next_event_no - 1:03d}"
        self.next_task_no += 1
        return f"TASK_{self.next_task_no - 1:03d}"

    def get(self, key: str) -> Optional[ItemRecord]:
        return self.items.get(key)

    # -- matching --------------------------------------------------------
    def match_key(self, canonical: str, kind_hint: Optional[str]) -> Tuple[Optional[str], float, str]:
        """Map a canonical capture onto a known key.

        Returns (key, confidence, method). method is one of
        exact | jaccard | containment | new. Ties above a small margin are
        deliberately not resolved (the caller then creates a latent item
        with status 'unclear').
        """
        cand_tokens = topic_tokens(canonical)
        if not cand_tokens:
            return None, 0.0, "empty"

        # 1) exact key match (highest confidence, no ambiguity, and the
        #    only path that may merge a task and an event on the same
        #    subject).
        if canonical in self.seed_keys:
            return canonical, 0.97, "exact"

        candidates = []
        for key in self.seed_keys:
            if kind_hint and self.seed_keys[key]["kind"] != "mixed" and \
                    self.seed_keys[key]["kind"] != kind_hint:
                continue
            known_tokens = topic_tokens(key)
            if not known_tokens:
                continue
            inter = len(set(cand_tokens) & set(known_tokens))
            union = len(set(cand_tokens) | set(known_tokens))
            jac = inter / union if union else 0.0
            candidates.append((key, known_tokens, jac))

        # 2) short containment: every content token of the capture is a
        #    subset of one known key (e.g. "model results" ->
        #    "review the model results").
        if len(cand_tokens) >= 2:
            contains = []
            for key, known_tokens, _ in candidates:
                if len(known_tokens) <= 3 * len(cand_tokens) and \
                        all(t in known_tokens for t in cand_tokens):
                    contains.append((key, len(known_tokens)))
            if len(contains) == 1:
                key, klen = contains[0]
                conf = max(0.55, 0.78 - 0.06 * max(0, klen - len(cand_tokens)))
                return key, conf, "containment"

        # 3) Jaccard similarity with a wide margin requirement.
        best = sorted(candidates, key=lambda c: c[2], reverse=True)[:2]
        if not best:
            return None, 0.0, "new"
        top, second = best[0], best[1] if len(best) > 1 else ("", [], 0.0)
        if top[2] >= 0.62 and (top[2] - second[2]) >= 0.18:
            conf = min(0.93, 0.60 + top[2])
            return top[0], round(conf, 2), "jaccard"
        if top[2] >= 0.62 and (top[2] - second[2]) < 0.18:
            return None, 0.5, "ambiguous"
        if top[2] >= 0.5 and len(top[1]) <= 2 * len(cand_tokens):
            conf = min(0.90, 0.55 + top[2])
            return top[0], round(conf, 2), "jaccard_loose"
        return None, 0.0, "new"

    # -- apply one message ----------------------------------------------
    def apply(self, message_id: str, timestamp: str, sender: str,
              body: str, category: str, extractor_title: Optional[str],
              extractor_is_pattern: bool, extractor_item: Optional[Dict],
              status_action: Optional[str], raw_text: str) -> Dict:
        """Resolve one message, update/create the item, return a summary."""
        kind_hint = None
        status_action = status_action or PENDING
        if extractor_item is not None:
            kind_hint = extractor_item["type"]

        # Topic phrase selection -------------------------------------------------
        phrase = None
        method = "extractor"
        conf = 0.9
        if extractor_is_pattern and extractor_title:
            canonical = canonical_phrase(extractor_title)
            if topic_tokens(canonical):
                phrase = canonical
                conf = 0.93
            else:
                phrase, conf = self._capture(body)
                method = "pattern"
        else:
            phrase, conf = self._capture(body)
            method = "pattern"

        if phrase is None:
            return {"resolved": False, "item": None, "key": None,
                    "status_action": status_action}

        key, match_conf, match_method = self.match_key(phrase, kind_hint)

        # A jaccard/containment match on a *new topic* still belongs to the
        # item registry only when it has a home; otherwise create a latent one.
        if key is None:
            # Ultra-generic single-token mentions ("the assignment",
            # "the meeting") are deliberately treated as unresolved so the
            # system never fabricates a topic from an ambiguous reference.
            if match_method != "ambiguous" and \
                    len(topic_tokens(phrase)) < 2:
                return {"resolved": False, "item": None, "key": None,
                        "status_action": status_action}
            # A new topic is only created from an extractor-backed item or
            # a dedicated task/event pattern. Plain information notices
            # (relocation, broadcast, generic status questions) that cannot
            # be tied to a known topic are treated as notices instead of
            # fabricating an item.
            if extractor_item is None and \
                    (category.get("category") if isinstance(category, dict)
                     else category) == "general_information" and \
                    status_action == PENDING and \
                    method == "pattern" and self.seed_keys:
                return {"resolved": False, "item": None, "key": None,
                        "status_action": status_action}
            key = phrase
            match_method = "new"
            match_conf = canonical_quality(phrase) if method == "pattern" else 0.8

        item = self.items.get(key)
        is_new = item is None
        if is_new:
            kind = kind_hint or ("event" if category == "meeting_or_event"
                                 else "task")
            item = ItemRecord(key, kind, extractor_title or phrase,
                              message_id, timestamp)
            # canonical item id: reuse the first L1 item id when it was the
            # seed (traceable), otherwise claim a fresh one.
            seed = self.seed_keys.get(key)
            if seed and (extractor_item is None or
                         seed["item_id"].startswith("TASK_") or
                         seed["item_id"].startswith("EVENT_")):
                item.item_id = seed["item_id"]
            else:
                item.item_id = self._claim_id(kind)
            if seed and seed["kind"] not in item.kind:
                item.kind = "task/event"
            self.items[key] = item
            self.order.append(key)
            # register the new topic so later messages can match it too.
            if key not in self.seed_keys:
                self.seed_keys[key] = {"kind": kind, "title": item.title,
                                       "item_id": item.item_id}

        if kind_hint and kind_hint not in item.kind.split("/"):
            item.kind = "task/event"
        if extractor_item:
            iid = extractor_item.get("item_id")
            if iid and iid not in item.related_item_ids:
                item.related_item_ids.append(iid)
                # the canonical id may already be the seed's first id
        if item.source_message_id is None:
            item.source_message_id = message_id
        if message_id not in item.message_ids:
            item.message_ids.append(message_id)
        item.last_update = timestamp
        item.resolution_confidence = min(0.98, max(
            item.resolution_confidence, conf * 0.7 + match_conf * 0.3))

        # Status bookkeeping -------------------------------------------------
        self._apply_status(item, message_id, timestamp, status_action, body)
        return {"resolved": True, "item": item, "key": key,
                "status_action": status_action, "is_new": is_new,
                "method": method + "/" + match_method,
                "resolution_confidence": item.resolution_confidence}

    def _capture(self, body: str) -> Tuple[Optional[str], float]:
        low = strip_prefixes(body)
        # generic status questions ("Was the compliance form approved ...?")
        q = re.search(
            r"^(?:was|is|did|has|have|are|were)\b\s+(?:the\s+)?(.+?)"
            r"\s+(?:approved|done|completed|handled|sent|submitted|scheduled)"
            r"\b[?.]*$", low, re.IGNORECASE)
        if q:
            phrase = q.group(1).strip()
            return canonical_phrase(phrase), 0.5
        for label, pattern, group, hint in REF_PATTERNS:
            m = re.search(pattern, low, re.IGNORECASE)
            if not m:
                continue
            raw = m.group(group).strip(" .,;:!?-")
            if not raw:
                continue
            canon = canonical_phrase(raw)
            if not canon:
                continue
            return canon, canonical_quality(raw)
        return None, 0.0

    def _apply_status(self, item: ItemRecord, message_id: str, timestamp: str,
                      status_action: str, body: str) -> None:
        """Update item status / deadlines / schedules from the message."""
        low = strip_prefixes(body)
        iso = find_iso_date(low)
        rel = self._relative_deadline(low)
        time_24 = find_time(low)

        # follow-up counter (request-style messages on an existing item)
        if status_action == PENDING and message_id != item.source_message_id:
            if re.search(r"\b(update|progress|status|started|handled|any)\b",
                         low, re.IGNORECASE):
                item.followup_count += 1

        # --- schedule / date changes -------------------------------------
        if status_action == "scheduled" and iso and time_24:
            change = self._register_schedule(item, message_id, timestamp, iso,
                                             time_24, low)
            if change:
                item.status_history.append({
                    "status": "scheduled",
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "reason": f"Schedule set/updated to {iso} at {time_24}.",
                })

        if status_action == "rescheduled":
            changed = False
            if iso and time_24:
                changed = self._register_schedule(item, message_id, timestamp,
                                                  iso, time_24, low)
            elif time_24:
                item.latest_time = time_24
                changed = True
            elif iso:
                changed = self._register_deadline(item, message_id, timestamp,
                                                  iso, low,
                                                  why="rescheduled")
            item.status = RESCHEDULED if changed else item.status
            item.status_history.append({
                "status": RESCHEDULED,
                "message_id": message_id,
                "timestamp": timestamp,
                "reason": "Event/meeting rescheduled by this message."
                          if changed else
                          "Reschedule announced without a concrete new "
                          "date/time.",
            })

        if status_action == "deadline_set":
            if iso:
                self._register_deadline(item, message_id, timestamp, iso, low,
                                        why="deadline_set")

        if status_action == "deadline_extended":
            if iso:
                self._register_deadline(item, message_id, timestamp, iso, low,
                                        why="deadline_extended")

        if status_action == "urgent":
            item.priority_history.append({
                "message_id": message_id,
                "timestamp": timestamp,
                "note": "Urgency explicitly raised ('treat this as urgent').",
            })
            rel = self._relative_deadline(low)
            if rel:
                item.deadline_history.append({
                    "from": item.latest_deadline,
                    "to": "unresolved",
                    "kind": "relative_deadline",
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "note": f"Deadline moved to '{rel}', relative to the "
                            f"message time; no concrete date is invented.",
                })
                item.latest_deadline = "unresolved"

        if status_action == "not_urgent":
            item.priority_history.append({
                "message_id": message_id,
                "timestamp": timestamp,
                "note": "Urgency explicitly lowered (may no longer be "
                        "urgent).",
            })

        # --- final overriding statuses -----------------------------------
        if status_action == "completed":
            self._apply_terminal(item, message_id, timestamp, COMPLETED)
        elif status_action == "cancelled":
            self._apply_terminal(item, message_id, timestamp, CANCELLED)
        elif status_action == "unclear":
            if item.status not in (COMPLETED, CANCELLED):
                item.status = UNCLEAR
            item.status_history.append({
                "status": UNCLEAR,
                "message_id": message_id,
                "timestamp": timestamp,
                "reason": "The message is ambiguous: " + self._reason_snip(low),
            })

        if status_action == "conflict":
            flags = [t for t in ("conflicting deadline",) if True]
            if iso and item.latest_deadline and item.latest_deadline != iso:
                item.conflicts.append({
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "type": "deadline_conflict",
                    "notes": "Message states a deadline that differs from "
                             "the previously recorded one.",
                })
                self._register_deadline(item, message_id, timestamp, iso, low,
                                        why="conflict")
            if not item.conflicts or \
                    item.conflicts[-1].get("message_id") != message_id:
                item.conflicts.append({
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "type": "conflicting_instruction",
                    "notes": self._reason_snip(low),
                })

        if status_action in (PENDING, "scheduled") and \
                item.status not in (COMPLETED, CANCELLED, UNCLEAR):
            if item.followup_count >= 2:
                item.status = IN_PROGRESS
                item.status_history.append({
                    "status": IN_PROGRESS,
                    "message_id": message_id,
                    "timestamp": timestamp,
                    "reason": "Repeated follow-ups indicate the item is "
                              "being worked on.",
                })

    @staticmethod
    def _relative_deadline(low: str) -> Optional[str]:
        m = re.search(r"\b(today|tomorrow|tonight)\b", low)
        return m.group(1) if m else None

    def _register_schedule(self, item: ItemRecord, message_id: str,
                           timestamp: str, iso: str, time24: str,
                           low: str) -> bool:
        changed = False
        if iso and iso != item.latest_deadline:
            item.deadline_history.append({
                "from": item.latest_deadline,
                "to": iso,
                "message_id": message_id,
                "timestamp": timestamp,
                "note": "Schedule date updated.",
            })
            item.latest_deadline = iso
            changed = True
        prev_time = item.latest_time
        item.latest_time = time24
        if prev_time != time24:
            item.deadline_history.append({
                "from": None,
                "to": time24,
                "kind": "time",
                "message_id": message_id,
                "timestamp": timestamp,
                "note": "Schedule time set/updated.",
            })
            changed = True
        loc = re.search(r"\bin\s+(zoom|google meet|conference room \d+|"
                        r"meeting room a)\b", low, re.IGNORECASE)
        if loc:
            item.latest_location = loc.group(1).lower()
            changed = True
        return changed

    def _register_deadline(self, item: ItemRecord, message_id: str,
                           timestamp: str, iso: str, low: str,
                           why: str) -> None:
        if item.latest_deadline == iso:
            return
        item.deadline_history.append({
            "from": item.latest_deadline,
            "to": iso,
            "message_id": message_id,
            "timestamp": timestamp,
            "note": f"Deadline updated ({why}).",
        })
        item.latest_deadline = iso

    def _apply_terminal(self, item: ItemRecord, message_id: str,
                        timestamp: str, status: str) -> None:
        item.status = status
        item.status_history.append({
            "status": status,
            "message_id": message_id,
            "timestamp": timestamp,
            "reason": "Status confirmed by the message text.",
        })

    @staticmethod
    def _reason_snip(low: str) -> str:
        snip = low[:90]
        snip = snip.rstrip(".")
        return snip + "."