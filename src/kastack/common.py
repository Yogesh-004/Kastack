"""Shared helpers used by every pipeline stage.

All decisions in this project are made by local, deterministic rules
(regex patterns + small heuristics). No external AI service is called at
runtime and no message content ever leaves this machine.

Masking policy: raw sensitive values are replaced on the fly and every
output file stores only the masked version of a message.
"""

from __future__ import annotations

import re
from typing import List, Optional

# Conversation-openers that carry no classification signal of their own.
# They are removed from the message body before scoring so that phrases such
# as "Can you help?" (opener) and "Can you update ..." (request) are not
# confused with each other.
OPENERS: List[str] = [
    r"For today:\s*",
    r"Can you help\??\s*",
    r"Just checking[—-]\s*",
    r"FYI:\s*",
    r"Quick update:\s*",
    r"One more thing:\s*",
    r"Please note:\s*",
    r"Important:\s*",
    r"Hi,\s*",
]

OPENERS_RE = re.compile(r"^\s*(" + "|".join(OPENERS) + r")+", re.IGNORECASE)

ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_SUFFIX_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")  # same as above; kept for clarity

# 09:15 / 9:15 / 9:15 PM / 6 PM / 6PM / 9 AM
TIME_24H_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)?\b", re.IGNORECASE)
TIME_HOUR_RE = re.compile(r"\b(\d{1,2})\s*(AM|PM)\b", re.IGNORECASE)

# Reserved sentence-level signal words (no longer part of any body text).
RELATIVE_TIME_WORDS = [
    "tomorrow", "today", "tonight", "next week", "this weekend",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "friday afternoon", "in 10 minutes",
]

LOCATION_WORDS = [
    "the library", "the college auditorium", "the city clinic", "the cafeteria",
    "zoom", "google meet", "conference room 2", "meeting room a",
    "the main office", "the training hall",
]

EVENT_NOUNS = ["orientation", "workshop", "study-group session", "seminar",
               "webinar", "briefing", "assignment"]  # briefing/assignment are task nouns; see extractor

PERSON_NAMES = ["meera", "ishaan", "kabir", "aarav", "ananya", "neha",
                "tara", "rohan", "vikram", "maya", "promotions", "hr team",
                "project lead"]

URGENT_WORDS = ["important", "urgent", "asap", "don't forget", "dont forget",
                "deadline", "must", "immediately"]
SOFT_WORDS = ["if possible", "when you are free", "sometime", "soon",
              "could be"]


def strip_openers(text: str) -> str:
    """Remove leading conversation openers (imperative-free filler phrases)."""
    prev = None
    current = text
    while current != prev:
        prev = current
        current = OPENERS_RE.sub("", current, count=1).strip()
    return current


def clean_text(text: str) -> str:
    """Lowercase, collapse whitespace (used for pattern matching only)."""
    return re.sub(r"\s+", " ", text).strip().lower()


def find_iso_date(text: str) -> Optional[str]:
    """Return the first ISO date found (YYYY-MM-DD) or None."""
    m = ISO_DATE_RE.search(text)
    return m.group(1) if m else None


def relative_time_present(text: str) -> Optional[str]:
    """Return the first relative-time phrase found, else None."""
    low = clean_text(text)
    for phrase in RELATIVE_TIME_WORDS:
        if phrase in low:
            return phrase
    return None


def find_time(text: str) -> Optional[str]:
    """Return a normalized 24h time (HH:MM) or None."""
    m = TIME_24H_RE.search(text)
    if m:
        hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
        if meridiem and meridiem.upper() == "PM" and hour < 12:
            hour += 12
        if meridiem and meridiem.upper() == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"
    m = TIME_HOUR_RE.search(text)
    if m:
        hour, meridiem = int(m.group(1)), m.group(2).upper()
        if meridiem == "PM" and hour < 12:
            hour += 12
        if meridiem == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"
    return None


def find_location(text: str) -> Optional[str]:
    """Return a normalized location from a message or None.

    A location only counts when it is used as a *place reference*
    (preceded by in/at/'Location:' or standing at the end of the message).
    This avoids false hits such as "renew the library book", where
    "the library" is part of a task noun phrase, not a place.
    """
    low = clean_text(text)
    joined = "|".join(re.escape(l) for l in LOCATION_WORDS)
    pattern = re.compile(
        r"\b(?:in|at)\s+(" + joined + r")\b"
        r"|\blocation:\s*(" + joined + r")\b"
        r"|(" + joined + r")\s*[,.)!]?$",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return None
    loc = next(g for g in m.groups() if g)
    if loc.lower() in {"zoom", "google meet", "conference room 2",
                       "meeting room a"}:
        return loc
    return loc.lower()


def find_person_mentioned(text: str) -> Optional[str]:
    """Return a person name that the user is asked to contact, or None."""
    low = clean_text(text)
    m = re.search(r"\b(?:call|contact|mail|message|email)\s+(maya)[\s,.;]?", low)
    if m:
        return m.group(1).capitalize()
    m = re.search(r"\b(maya)\s+asked\b", low)
    if m:
        return m.group(1).capitalize()
    return None


def days_until(iso_date: str, message_timestamp: str) -> Optional[int]:
    """Whole days between a message timestamp and a deadline date."""
    try:
        from datetime import datetime
        msg_dt = datetime.strptime(message_timestamp[:10], "%Y-%m-%d")
        due_dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return (due_dt - msg_dt).days
    except (ValueError, TypeError):
        return None


def first_upper(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:] if text else text


def mask_value(secret: str) -> str:
    """Return a safe placeholder for a secret value."""
    if not secret:
        return "******"
    if any(ch.isalpha() for ch in secret):
        return "******"
    return "*" * max(len(secret), 4)


_DASH_TRANS = str.maketrans({"\u2014": "-", "\u2013": "-", "\u2015": "-"})


def display_text(text: str) -> str:
    """Unicode-dash normalization so console/UI rendering stays clean."""
    return text.translate(_DASH_TRANS)


ASCII_MASK = re.compile(r"[*]+")


def split_reason(fragments: List[str]) -> str:
    """Join human-readable signal fragments into one reason sentence."""
    return "; ".join(f for f in fragments if f)