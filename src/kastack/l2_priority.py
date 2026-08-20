"""L2 Part 1 - Priority and action engine.

Extends the L1 heuristic three-level priority (high/medium/low) with the
assignment's four-level scheme (critical/high/medium/low) plus two things
the L1 pipeline could not do:

* *state awareness* — the deadline used for "proximity" is the *current*
  deadline of the canonical item (updated by deadline-change messages),
  not just the first date in the message;
* *priority updates* — every later message that changes the deadline,
  urgency or status of an item re-evaluates the item's priority, so the
  history shows the item moving between levels over time.

The score is a transparent sum of weighted signals:

    base_score        every actionable or status-carrying message starts
                      with a small base that reflects its kind
    overdue           deadline already passed (open item)          +70
    due_today         deadline is the message date                 +40
    due_tomorrow      deadline is the next day (ISO or relative)   +35
    proximity         +5..+25 for deadlines within 1-7 days        +5..+25
    urgency           urgent/asap/immediately/treat as urgent      +25
                      important/ must / don't forget               +10
    deadline_pull_in  "earlier than previously planned"            +20
    deadline_extended new deadline farther away                    -10
    deadline_conflict message contradicts the recorded deadline    +15
    response_required "please confirm"/"is it in progress"/...     +10
    sender_authority  Project Lead / Mentor / HR Team              +15
    sensitive         high-risk secret value present               +15
    repeated_followups 2+ follow-ups since creation                +5 each

Thresholds:  critical >= 75, high >= 50, medium >= 25, low < 25.
A message that marks an item as completed or cancelled is not an action
request any more: it receives priority "low" with signal "status_resolved".

Every decision stores message_id, item_id, priority, reason, signals and a
confidence computed from the number of strong signals, deadline
explicitness and resolution confidence. Nothing here invents data: when no
item can be identified the decision is simply not emitted (the message is
recorded on the noticeboard instead).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .common import days_until
from .l2_core import (
    COMPLETED,
    CANCELLED,
    IN_PROGRESS,
    PENDING,
    RESCHEDULED,
    UNCLEAR,
    ItemRecord,
)

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

_URGENT_STRONG = re.compile(
    r"\b(urgent|asap|immediately|right away|treat\s+this\s+as\s+urgent)\b",
    re.IGNORECASE)
_URGENT_WEAK = re.compile(
    r"\b(important|don'?t\s+forget|must|no\s+longer\s+optional)\b",
    re.IGNORECASE)
_RESPONSE_REQUIRED = re.compile(
    r"please\s+confirm\b|confirm\s+whether\b|is\s+it\s+in\s+progress\??|"
    r"any\s+(update|progress)\b|check\s+the\s+latest\s+status\b|"
    r"has\s+the\b[^.]{0,60}\?|been\s+handled\s+yet\b|"
    r"share\s+an\s+update\b", re.IGNORECASE)
_PULL_IN = re.compile(r"earlier\s+than\s+previously\s+planned", re.IGNORECASE)
_EXTENDED = re.compile(r"\bextended\s+to\b", re.IGNORECASE)
_RELATIVE_SOON = re.compile(r"\b(tomorrow|today|tonight)\b", re.IGNORECASE)

_AUTHORITY_SENDERS = {"project lead", "mentor", "hr team"}
_NOISE_SENDERS = {"promotions", "general updates", "private message"}
_UNKNOWN_SENDERS = {"unknown sender"}

SIGNAL_LABELS = {
    "overdue": "overdue",
    "due_today": "deadline_today",
    "due_tomorrow": "deadline_tomorrow",
    "proximity": "deadline_within_7_days",
    "urgency": "urgent",
    "important": "important",
    "pull_in": "deadline_pulled_in",
    "extended": "deadline_extended",
    "conflict": "deadline_conflict",
    "response_required": "response_required",
    "sender_authority": "sender_authority",
    "sensitive": "high_risk_sensitive_value",
    "followups": "repeated_followups",
    "status_resolved": "status_resolved",
    "priority_persisted": "priority_persisted",
    "urgency_removed": "urgency_removed",
    "deadline_today_relative": "deadline_today_relative",
}


def detect_status_action(text: str) -> str:
    """Map a raw message onto the status it imposes on the item it refers
    to. Most specific patterns are checked first; patterns that only add
    *signals* (urgency, pull-in) are handled by the scoring step, not here.
    """
    low = re.sub(r"[^\w\s\-:]+", " ", text.lower())
    if re.search(r"\bhas been completed successfully\b", low) or (
            re.search(r"\bconfirmed\s*:\s*", low) and
            re.search(r"\bhas been completed\b", low)):
        return COMPLETED
    if re.search(r"\bis no longer (required|needed)\b", low) or \
            re.search(r"\byou can cancel\b|\bcancel\b[^.]{0,60}no longer\b",
                      low) or \
            re.search(r"\bhas been cancelled\b", low):
        return CANCELLED
    if re.search(r"\bmoved to\b[^.]*\d{4}-\d{2}-\d{2}", low) or \
            re.search(r"\bthe time is now\b", low):
        return RESCHEDULED
    if re.search(r"\bmay no longer be urgent\b", low):
        return "not_urgent"
    if re.search(r"\bmight already be\b|\bcannot confirm\b|"
                 r"\bnot completely sure\b|\bprobably handled\b", low) or \
            re.search(r"\bmay move\b|\bwill confirm the schedule later\b|"
                      r"\bwait for the official update\b", low):
        return UNCLEAR
    if re.search(r"\bwait for confirmation\b", low) or \
            re.search(r"\bthe latest instruction says\b", low) or \
            re.search(r"\balthough the earlier message listed another date\b",
                      low):
        return "conflict"
    if re.search(r"\bhas been extended to\b", low):
        return "deadline_extended"
    if re.search(r"\btreat this as urgent\b", low) or \
            re.search(r"\bthe deadline to\b[^.]{0,120}\bis now\b", low):
        return "urgent"
    if re.search(r"\bscheduled for\b", low):
        return "scheduled"
    if re.search(r"\bis due on\b", low) or \
            re.search(r"\bplease note that\b", low):
        return "deadline_set"
    return PENDING


def _score_to_priority(score: int) -> str:
    if score >= 75:
        return CRITICAL
    if score >= 50:
        return HIGH
    if score >= 25:
        return MEDIUM
    return LOW


def _days_to(timestamp: str, iso_date: Optional[str]) -> Optional[int]:
    if not iso_date:
        return None
    return days_until(iso_date, timestamp)


def evaluate(item: Optional[ItemRecord], message_id: str, timestamp: str,
             sender: str, category: str, text: str, status_action: str,
             high_risk_sensitive: bool) -> Optional[Dict]:
    """Compute the priority decision for one message.

    A decision is only emitted when the message can be tied to an
    identified task or event. Messages that cannot be tied to any item
    (ambiguous notices, uncategorised status updates) are recorded on the
    noticeboard instead of receiving a fabricated priority.
    """
    if item is None:
        return None

    sender_low = sender.strip().lower()
    score = 0
    signals: List[str] = []
    reason_parts: List[str] = []
    deadline = item.latest_deadline
    terminal = status_action in (COMPLETED, CANCELLED)

    # 1) base score by message kind -------------------------------------
    if status_action in (COMPLETED, CANCELLED, UNCLEAR, "not_urgent",
                         "conflict"):
        score += 5
    elif item.source_message_id == message_id:
        score += 20                       # new task / event creation
        signals.append("new_item")
    elif item.followup_count >= 1:
        score += 8                        # follow-up or status touch
        signals.append("follow_up")
    else:
        score += 12

    # 2) status-resolved messages are not action requests ---------------
    if terminal:
        signals = ["status_" + (COMPLETED if status_action == COMPLETED
                                else CANCELLED), "no_action_needed"]
        reason = (
            f"The message confirms the item as {status_action}; no further "
            f"action is required, so the priority is {LOW}.")
        conf = 0.78 if status_action == COMPLETED or \
            status_action == CANCELLED else 0.72
        return {
            "message_id": message_id,
            "item_id": item.item_id if item else None,
            "priority": LOW,
            "reason": reason,
            "signals": signals,
            "confidence": conf,
        }

    # 3) deadline proximity (relative to the message timestamp) ----------
    d = _days_to(timestamp, deadline)
    if d is not None and d < 0 and item.status not in (COMPLETED,
                                                       CANCELLED):
        score += 70
        signals.append(SIGNAL_LABELS["overdue"])
        reason_parts.append(f"deadline {deadline} has already passed "
                            f"{abs(d)} day(s) ago")
    elif d == 0:
        score += 40
        signals.append(SIGNAL_LABELS["due_today"])
        reason_parts.append("deadline is today")
    elif d == 1:
        score += 35
        signals.append(SIGNAL_LABELS["due_tomorrow"])
        reason_parts.append("deadline is tomorrow")
    elif d is not None and 2 <= d <= 7:
        score += 25 - 5 * (d - 2)         # 25..5
        signals.append(SIGNAL_LABELS["proximity"])
        reason_parts.append(f"deadline in {d} day(s)")
    elif d is not None and 8 <= d <= 14:
        score += 5
        signals.append("deadline_within_14_days")

    rel = _RELATIVE_SOON.findall(text)
    if rel and d is None:
        phr = rel[0].lower()
        score += 35 if phr == "tomorrow" else 30
        signals.append(SIGNAL_LABELS["due_tomorrow"] if phr == "tomorrow"
                       else "deadline_today_relative")
        reason_parts.append(f"deadline is near ('{phr}', relative to the "
                            f"message time)")

    # 4) urgency wording --------------------------------------------------
    if _URGENT_STRONG.search(text):
        score += 25
        signals.append(SIGNAL_LABELS["urgency"])
        reason_parts.append("message marks the item as urgent")
    if _URGENT_WEAK.search(text):
        score += 10
        signals.append(SIGNAL_LABELS["important"])
        reason_parts.append("message uses importance wording")

    # 5) deadline change signals ------------------------------------------
    if status_action == "not_urgent":
        score -= 15
        signals.append("urgency_removed")
        reason_parts.append("message states the item may no longer be "
                            "urgent")
    if _PULL_IN.search(text):
        score += 20
        signals.append(SIGNAL_LABELS["pull_in"])
        reason_parts.append("deadline was pulled in earlier than planned")
    if _EXTENDED.search(text):
        score -= 10
        signals.append(SIGNAL_LABELS["extended"])
        reason_parts.append("deadline was extended")
    if status_action == "conflict":
        score += 15
        signals.append(SIGNAL_LABELS["conflict"])
        reason_parts.append("message contradicts an earlier deadline")

    # 6) response required ------------------------------------------------
    if _RESPONSE_REQUIRED.search(text):
        score += 10
        signals.append(SIGNAL_LABELS["response_required"])
        reason_parts.append("message explicitly requests a response")

    # 7) sender authority --------------------------------------------------
    if sender_low in _AUTHORITY_SENDERS:
        score += 15
        signals.append(SIGNAL_LABELS["sender_authority"])
        reason_parts.append(f"authoritative sender ({sender})")
    elif sender_low in _NOISE_SENDERS:
        score -= 5
    elif sender_low in _UNKNOWN_SENDERS:
        score += 3

    # 8) high-risk sensitive value --------------------------------------
    if high_risk_sensitive:
        score += 15
        signals.append(SIGNAL_LABELS["sensitive"])
        reason_parts.append("message carries a high-risk secret value")

    # 9) repeated follow-ups ----------------------------------------------
    if item is not None and item.followup_count >= 2:
        extra = min(20, 5 * (item.followup_count - 1))
        score += extra
        signals.append(SIGNAL_LABELS["followups"])
        reason_parts.append(
            f"item has received {item.followup_count} follow-up messages")

    priority = _score_to_priority(score)
    if status_action == UNCLEAR and item is not None:
        # Uncertainty about the *status* says nothing about urgency: it must
        # not silently downgrade an item that was already critical/high.
        priority = item.priority
        signals.append("uncertainty_keeps_priority")
        reason_parts.append(
            "status is uncertain; no urgency change was stated, so the "
            "existing priority is kept")
    signals = list(dict.fromkeys(signals))
    if item is not None and item.priority == priority:
        signals.append(SIGNAL_LABELS["priority_persisted"])

    # 10) confidence ------------------------------------------------------
    strong = sum(1 for s in signals
                 if s not in ("priority_persisted", "follow_up", "new_item"))
    base = 0.5 + 0.08 * min(6, strong)
    if deadline:
        base += 0.10
    if item is not None:
        base += 0.10 * min(1.0, item.resolution_confidence)
    conf = round(max(0.50, min(0.97, base)), 2)

    if not reason_parts:
        reason_parts.append("no strong urgency or deadline signals")
    reason = ("Priority {pri}: {parts}; a later message may update it."
              .format(pri=priority, parts="; ".join(reason_parts)))
    if SIGNAL_LABELS["priority_persisted"] in signals:
        reason += " Priority unchanged since the previous decision."

    return {
        "message_id": message_id,
        "item_id": item.item_id if item else None,
        "priority": priority,
        "reason": reason,
        "signals": signals,
        "confidence": conf,
    }