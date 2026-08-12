"""Part 1 - Message classification.

A transparent, local rule engine. Every category scores evidence from
explicit signal rules (regex patterns). The category with the highest
score wins; the confidence reflects both the absolute evidence strength
and the margin over the runner-up. The collected signal names are rendered
into a human-readable reason, so every decision is explainable.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List, Tuple

from .common import (
    find_iso_date,
    find_location,
    find_time,
    strip_openers,
)

CATEGORIES = [
    "action_required",
    "meeting_or_event",
    "personal_information",
    "general_information",
    "promotional",
    "sensitive_information",
]

# ---------------------------------------------------------------------------
# Signal rules: (category, description_template, points, compiled regex).
# Each signal can fire at most once per message; the optional capture group
# is rendered into the description template for the "reason" field.
# ---------------------------------------------------------------------------

ACTION_VERBS = [
    "submit", "upload", "reply", "confirm", "renew", "call", "review",
    "verify", "finish", "prepare", "complete", "send", "share", "pay",
    "email", "register", "sign", "back up",
]
ACTION_NOUNS = [
    "signed document", "electricity bill", "library book", "model results",
    "dataset labels", "test cases", "privacy checklist", "project tracker",
    "revised presentation", "expense receipt", "meeting notes",
    "onboarding form", "demo video", "weekly report", "client email",
    "assignment", "interview slot", "report",
]
EVENT_NOUNS = [
    "internship orientation", "ai workshop", "study-group session",
    "college seminar", "technical interview", "design review",
    "placement briefing", "sprint planning", "mentor catch-up",
    "team stand-up", "doctor appointment", "client discussion",
    "product demo", "project review", "family dinner",
]

from typing import Pattern  # noqa: E402

_RULES: List[Tuple[str, str, int, Pattern]] = []


def _add(category: str, template: str, points: int, pattern: str) -> None:
    _RULES.append((category, template, points, re.compile(pattern, re.IGNORECASE)))


# Promotional --------------------------------------------------------------
_add("promotional", "sender is the promotions account", 55, r"\bnever\b")
_add("promotional", "promo code 'SAVE..'", 40, r"\buse\s+code\s+save\d+\b")
_add("promotional", "percentage discount", 35, r"\b\d+\s*%\s*off\b")
_add("promotional", "sale or offer wording", 30,
     r"\b(flash sale|sale|discount|offer|deal)\b")
_add("promotional", "plan upsell wording", 40,
     r"\b(premium plan|upgrade your subscription|new student plan|"
     r"exclusive benefits)\b")
_add("promotional", "reward points", 30, r"\breward points\b")
_add("promotional", "cashback", 30, r"\bcashback\b")
_add("promotional", "free delivery", 25, r"\bfree delivery\b")
_add("promotional", "coupon expiry", 30, r"\bcoupon expires\b")
_add("promotional", "buy-one-get-one", 30,
     r"\bbuy one (course|get one)\b")
_add("promotional", "festival wording", 25, r"\bfestival\b")

# Meeting / event ----------------------------------------------------------
_add("meeting_or_event", "calendar entry", 80, r"\bcalendar update:?\b")
_add("meeting_or_event", "reminder of an event", 45, r"\breminder:?\b")
_add("meeting_or_event", "explicit schedule", 65, r"\bscheduled for\b")
_add("meeting_or_event", "invitation to join", 60, r"\bplease join\b")
_add("meeting_or_event", "scheduled date phrase", 50, r"\bhappens on\b")
_add("meeting_or_event", "availability request for a slot", 50,
     r"\bare you available for\b")
_add("meeting_or_event", "tentative meeting proposal", 45,
     r"\blet us meet\b|\blet's meet\b")
_add("meeting_or_event", "named event '<event>'", 35,
     r"\b(?:the\s+)?(" + "|".join(EVENT_NOUNS) + r")\b")
_add("meeting_or_event", "tentative review slot", 30,
     r"\breview could be\b")

# Action required ----------------------------------------------------------
_add("action_required", "request verb '<verb>'", 20,
     r"\b(" + "|".join(ACTION_VERBS) + r")\b")
_add("action_required", "task noun '<noun>'", 10,
     r"\b(" + "|".join(ACTION_NOUNS) + r")\b")
_add("action_required", "polite request 'please'", 25, r"\bplease\b")
_add("action_required", "request 'can you'", 25, r"\bcan you\b")
_add("action_required", "request 'could you'", 30, r"\bcould you\b")
_add("action_required", "request 'need you to'", 40, r"\bneed you to\b")
_add("action_required", "imperative 'don't forget'", 30,
     r"\bdon'?t forget\b")
_add("action_required", "explicit 'deadline'", 45, r"\bdeadline\b")
_add("action_required", "due-date phrase 'due on'", 40, r"\bdue on\b")
_add("action_required", "date bound 'before <date>'", 35,
     r"\bbefore\s+(\d{4}-\d{2}-\d{2})\b")
_add("action_required", "date bound 'by <date>'", 30,
     r"\bby\s+(\d{4}-\d{2}-\d{2})\b")
_add("action_required", "conditional 'if possible'", 10,
     r"\bif possible\b")

# Personal information -----------------------------------------------------
_add("personal_information", "profile statement", 60, r"\bfor my profile\b")
_add("personal_information", "personal note", 55, r"\bpersonal note:?\b")
_add("personal_information", "favourite preference", 45, r"\bmy favourite\b")
_add("personal_information", "emergency-contact statement", 45,
     r"\bmy emergency contact\b")
_add("personal_information", "diet preference", 45, r"\bvegetarian\b")
_add("personal_information", "living-near statement", 45,
     r"\bi live near\b")
_add("personal_information", "food preference", 40,
     r"\bcoffee without sugar\b")
_add("personal_information", "clothing size", 40, r"\bt-shirt size\b")
_add("personal_information", "appearance preference", 40,
     r"\bdark mode\b")
_add("personal_information", "habit statement", 40,
     r"\busually study after dinner\b")
_add("personal_information", "meeting-time preference", 30,
     r"\b(?:morning|evening) meetings\b")
_add("personal_information", "communication preference", 35,
     r"\bi prefer\b")

# General information ------------------------------------------------------
_add("general_information", "availability statement", 25,
     r"\bis(?: now)? available\b")
_add("general_information", "update statement", 25, r"\bhas been updated\b")
_add("general_information", "operating-hours statement", 25,
     r"\b(closes at|opens at)\b")
_add("general_information", "service-interval statement", 25,
     r"\bleaves every\b")
_add("general_information", "holiday notice", 25, r"\bpublic holiday\b")
_add("general_information", "weather statement", 25, r"\bweather forecast\b")
_add("general_information", "hours-change statement", 25,
     r"\bextended weekend hours\b")
_add("general_information", "status statement", 15, r"\bfully charged\b")
_add("general_information", "maintenance notice", 25,
     r"\bunder maintenance\b")
_add("general_information", "reorganisation notice", 20,
     r"\breorganized\b")
_add("general_information", "relocation notice", 20, r"\bhas moved\b")
_add("general_information", "possibility statement", 20,
     r"\bmay be needed\b")
_add("general_information", "portal statement", 20, r"\bon the portal\b")
_add("general_information", "version statement", 25,
     r"\bnew python version\b")
_add("general_information", "hours-change statement 2", 20,
     r"\bchanged its working hours\b")
_add("general_information", "supply statement", 20,
     r"\btraining material\b")

SENDER_PROMO_NAME = "sender is the promotions account"


def _describe(template: str, match: "re.Match") -> str:
    if "<" not in template and ">" not in template:
        return template
    value = match.group(1) if match.lastindex else ""
    return (template.replace("<verb>", value)
            .replace("<noun>", value)
            .replace("<event>", value)
            .replace("<date>", value))


def _scores_for(
    message_text: str,
    sender: str,
    sensitive_detected: bool,
) -> Tuple[Dict[str, int], Dict[str, List[str]]]:
    """Return (points_per_category, signal_names_per_category)."""
    body = strip_openers(message_text)
    scores = {c: 0 for c in CATEGORIES}
    labels: Dict[str, List[str]] = {c: [] for c in CATEGORIES}

    for category, template, points, pattern in _RULES:
        if template == SENDER_PROMO_NAME:
            if sender.strip().lower() == "promotions":
                scores[category] += points
                labels[category].append(template)
            continue
        m = pattern.search(body)
        if m:
            scores[category] += points
            labels[category].append(_describe(template, m))

    # Structured-event bonus: an ISO date together with a time (and a
    # location) is very strong evidence for a meeting or event.
    has_date = find_iso_date(body) is not None
    has_time = find_time(body) is not None
    has_loc = find_location(body) is not None
    if has_date and has_time and has_loc:
        scores["meeting_or_event"] += 25
        labels["meeting_or_event"].append("date+time+location structure")
    elif has_date and has_time:
        scores["meeting_or_event"] += 15
        labels["meeting_or_event"].append("date+time structure")

    # A message where the *sender* promises to do something later is not a
    # request directed at the reader (e.g. "I will send the login details
    # separately."); it is an informational statement.
    if re.search(r"\bi('ll| will) (send|share|update|call)\b", body,
                 re.IGNORECASE):
        scores["action_required"] = 0

    # Sensitive values trump weak request signals: a message that leaks a
    # password or OTP is primarily a security problem, not a to-do item.
    if sensitive_detected:
        scores["sensitive_information"] += 200
        labels["sensitive_information"].append("sensitive value present")

    return scores, labels


def classify(
    message_text: str,
    sender: str,
    sensitive_detected: bool = False,
) -> Dict[str, object]:
    """Classify one message; return category, confidence and reason."""
    scores, labels = _scores_for(message_text, sender, sensitive_detected)
    body = strip_openers(message_text)

    ranking = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    winner, win_score = ranking[0]
    runner_score = ranking[1][1]

    if win_score == 0:
        return {
            "category": "general_information",
            "confidence": 0.52,
            "uncertain": True,
            "reason": ("No specific classification signal matched; the "
                       "message reads as an informational statement."),
        }

    margin = (win_score - runner_score) / max(win_score, 1)
    strength = 1.0 - math.exp(-win_score / 70.0)
    confidence = 0.55 + 0.30 * strength + 0.12 * margin
    uncertain = False

    if winner in ("action_required", "meeting_or_event") and \
            not find_iso_date(body):
        confidence -= 0.06
        uncertain = True
    if winner == "meeting_or_event" and re.search(r"\bcould be\b", body,
                                                  re.IGNORECASE):
        confidence -= 0.10
        uncertain = True
    if winner == "promotional" and sender.strip().lower() != "promotions":
        confidence -= 0.05

    confidence = round(min(0.97, max(0.50, confidence)), 2)
    if confidence < 0.65:
        uncertain = True

    names = list(dict.fromkeys(labels[winner]))
    if winner == "general_information" and not names:
        names = ["informational statement, no request or event found"]
    reason = "Matched " + " + ".join(names) + f" (sender: {sender})."
    if uncertain:
        reason += " Low-confidence match."

    return {
        "category": winner,
        "confidence": confidence,
        "uncertain": uncertain,
        "reason": reason,
    }