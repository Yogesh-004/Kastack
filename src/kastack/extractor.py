"""Part 2 - Task and event extraction.

Messages classified as "action_required" produce a TASK item; messages
classified as "meeting_or_event" produce an EVENT item.

Design rules (important for the assignment):
  * Missing information is never invented. A field that cannot be resolved
    is stored as null; a *relative* phrase (tomorrow, next week, Friday
    afternoon, soon) is stored as "unresolved" together with a note.
  * The deadline / date uses the first explicit ISO date (YYYY-MM-DD).
  * Time is normalised to 24h "HH:MM"; the venue is normalised.
  * Priority is a heuristic: urgency words or a deadline within 7 days of
    the message timestamp => high; soft words (if possible / when you are
    free / sometime / soon) => low; otherwise medium.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .common import (
    SOFT_WORDS,
    URGENT_WORDS,
    days_until,
    find_iso_date,
    find_location,
    find_person_mentioned,
    find_time,
    first_upper,
    relative_time_present,
    strip_openers,
)

UNRESOLVED = "unresolved"
ISO_DATE = r"\d{4}-\d{2}-\d{2}"


def contains_any(text: str, words: List[str]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _event_title(body: str) -> str:
    rules = [
        (r"calendar update:?\s*([^,]+,?)", 1),
        (r"reminder:?\s*([^,]+?)\s+(?:happens on|is on)\b", 1),
        (r"please join\s+(?:the\s+)?([^,]+?)\s+(?:on|\,)", 1),
        (r"are you available for\s+(?:the\s+)?([^?]+?)\s+at\b", 1),
        (r"([^,]+?)\s+is scheduled for\s+" + ISO_DATE, 1),
        (r"review could be\b", None),
        (r"let us meet\b|\blet's meet\b", None),
    ]
    for pattern, group in rules:
        m = re.search(pattern, body, re.IGNORECASE)
        if not m:
            continue
        if group is None:
            if "review could be" in body.lower():
                return "Review (tentative)"
            return "Team meeting (tentative)"
        title = m.group(group).strip(" ,")
        title = re.sub(r"\bthe\s+", "", title, count=1, flags=re.IGNORECASE)
        title = title.rstrip(",:").strip()
        if title:
            return first_upper(title)
    fallback = re.sub(r"\s+", " ", body)[:70]
    return first_upper(fallback.rstrip("."))


def _task_title(body: str) -> str:
    rules = [
        # "Don't forget to email the signed document; deadline is ..."
        (r"don'?t forget to\s+(.+?)\s*;\s*deadline\b", None),
        # "Complete the onboarding form is due on 2026-09-10."
        (r"(.+?)\s+is due on\s+" + ISO_DATE, 1),
        # "I need you to renew the library book by 2026-09-08."
        # "Please join-invites never reach here (events only).
        (r"(?:i need you to|can you|could you)\s+(.+?)\s+(?:by|before)\s+"
         + ISO_DATE, 1),
        # "Please submit the weekly report by 2026-09-05."
        (r"please\s+(.+?)\s+by\s+" + ISO_DATE, 1),
        # "Send the expense receipt is due on ..." is covered above; also
        # "Submit the weekly report is due on ..." style variants.
        (r"(.+?)\s*;\s*deadline is\s+" + ISO_DATE, 1),
        # "Please call Maya when you are free."
        (r"please\s+(call\s+maya)", 1),
        # "Could you send it soon?"
        (r"(?:can you|could you)\s+(send\s+it\b)[^,.;]*", 1),
    ]
    for pattern, group in rules:
        m = re.search(pattern, body, re.IGNORECASE)
        if not m:
            continue
        title = m.group(group) if group else m.group(0)
        title = re.sub(r"\b(don'?t forget to|please|can you|could you|"
                       r"i need you to)\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*(by|before)\s*" + ISO_DATE + r"\s*$", "", title)
        title = re.sub(r"\s*;\s*(deadline|due).*$", "", title)
        title = title.strip(" .,;:")
        if title:
            return first_upper(title)
    fallback = re.sub(r"\s+", " ", body)
    fallback = re.sub(r"^if possible[,\s]+", "", fallback, flags=re.IGNORECASE)
    fallback = re.sub(r"\s*(;|by|before)\s*" + ISO_DATE + r".*$", "",
                      fallback).strip(" .,;")
    return first_upper(fallback[:70].rstrip(".")) or "Action item"


def _resolve_date(text: str) -> Dict[str, Optional[str]]:
    iso = find_iso_date(text)
    if iso:
        return {"value": iso, "notes": []}
    rel = relative_time_present(text)
    if rel:
        return {
            "value": UNRESOLVED,
            "notes": [
                f"Relative time phrase '{rel}' cannot be resolved to a "
                f"concrete date without external context."
            ],
        }
    return {"value": None, "notes": []}


def _priority(raw_text: str, iso_date: Optional[str], timestamp: str) -> str:
    low = raw_text.lower()
    if contains_any(low, URGENT_WORDS):
        return "high"
    if iso_date:
        remain = days_until(iso_date, timestamp)
        if remain is not None and 0 <= remain <= 7:
            return "high"
    if contains_any(low, SOFT_WORDS):
        return "low"
    return "medium"


def extract(
    message_id: str,
    message_text: str,
    sender: str,
    timestamp: str,
    category: str,
) -> List[Dict[str, object]]:
    """Extract zero or one structured item for a classified message."""
    if category not in ("action_required", "meeting_or_event"):
        return []

    body = strip_openers(message_text)
    is_event = category == "meeting_or_event"

    if is_event:
        title = _event_title(body)
        date_info = _resolve_date(body)
        type_name = "event"
    else:
        title = _task_title(body)
        date_info = _resolve_date(body)
        type_name = "task"

    deadline_value = date_info["value"]
    frac_date = deadline_value if isinstance(deadline_value, str) and \
        deadline_value != UNRESOLVED else None

    item: Dict[str, object] = {
        "type": type_name,
        "title": title,
        "description": message_text,           # masked by the pipeline
        "deadline": deadline_value,             # ISO date | "unresolved" | null
        "time": find_time(body),
        "person": find_person_mentioned(message_text),
        "priority": _priority(message_text, frac_date, timestamp),
        "location": find_location(body) if is_event else None,
        "notes": list(date_info["notes"]),
        "source_message_id": message_id,
    }
    return [item]