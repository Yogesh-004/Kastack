"""L2 - Privacy-aware routing.

Every request (a new message to process, or a user question the assistant
must answer) is routed by an explicit policy before anything is sent
anywhere:

  * **blocked**                 the evidence contains a *high-risk* secret
                                (password, OTP, token, card, bank account,
                                recovery code). The request must not leave
                                the local machine.
  * **ask_for_confirmation**    the evidence needs human approval first:
                                medium-risk values whose recommended action
                                is ``ask_for_confirmation`` (health info,
                                ID number) or a message whose status is
                                ambiguous enough that processing it silently
                                could be wrong.
  * **process_locally**         everything else (incl. medium-risk values
                                whose action is ``safe_to_process_locally``
                                such as home address / phone number).

The route check never needs the raw value: it uses the *type and risk* of
the L1 sensitive detection, and the excerpted evidence shown to the user is
always the masked text.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .l2_priority import detect_status_action
from .l2_core import UNCLEAR
from .sensitive import detect_sensitive

BLOCKED = "blocked"
CONFIRM = "ask_for_confirmation"
LOCAL = "process_locally"

# Sensitive types whose recommended_action is ask_for_confirmation.
_NEED_APPROVAL = {"health_information", "personal_identification_number"}
# Sensitive types whose risk is high (block).
_HIGH_RISK_BLOCK = {True}  # risk field == "high"


def _sensitive_summary(text: str) -> List[Dict]:
    found = []
    for d in detect_sensitive(text):
        found.append({
            "type": d["sensitivity_type"],
            "risk": d["risk"],
            "action": d["recommended_action"],
        })
    return found


def decide_message(message_id: str, text: str, timestamp: str,
                   sender: str) -> Dict:
    """Route one incoming raw message (content is never stored)."""
    dets = _sensitive_summary(text)
    ambiguous = detect_status_action(text) == UNCLEAR
    signals: List[str] = []

    if any(d["risk"] == "high" for d in dets):
        route = BLOCKED
        signals.append(f"high_risk_{_names(dets)}")
        reason = ("Contains a high-risk secret value; it must not be sent "
                  "to any external service or stored.")
        conf = 0.92
    elif any(d["type"] in _NEED_APPROVAL for d in dets):
        route = CONFIRM
        signals.append(f"needs_approval_{_names(dets)}")
        reason = ("Contains sensitive data whose policy requires explicit "
                  "confirmation before processing.")
        conf = 0.85
    elif ambiguous:
        route = CONFIRM
        signals.append("status_ambiguous")
        reason = ("The message is ambiguous about its status; processing "
                  "it silently could be wrong, so confirmation is asked.")
        conf = 0.70
    elif dets:
        route = LOCAL
        signals.append(f"local_ok_{_names(dets)}")
        reason = ("Contains low/medium-risk data that the policy marks as "
                  "safe to process locally.")
        conf = 0.75
    else:
        route = LOCAL
        signals.append("no_sensitive_value")
        reason = "No sensitive value detected; safe to process locally."
        conf = 0.70

    masked = _mask(present(text))

    return {
        "request_id": message_id,
        "kind": "message",
        "timestamp": timestamp,
        "sender": sender,
        "route": route,
        "reason": reason,
        "signals": signals,
        "masked_evidence": masked[:160],
        "sensitive_found": dets,
        "confidence": conf,
    }


def _names(dets: List[Dict]) -> str:
    return "_".join(sorted({d["type"] for d in dets}))


def _mask(text: str) -> str:
    from .sensitive import mask_message
    secrets = [d["secret"] for d in detect_sensitive(text)]
    return mask_message(text, secrets)


def present(text: str) -> str:
    return text


def decide_query(query_id: str, query: str, evidence: List[Dict],
                 evidence_sensitive: List[Dict]) -> Dict:
    """Route one assistant request.

    `evidence_sensitive` is the aggregated sensitive detection summary of
    the evidence messages the answer would use.
    """
    asks_for_secret = bool(re.search(
        r"\b(password|otp|token|card|bank account|recovery code|"
        r"identification number|secret)\b", query, re.IGNORECASE))
    signals: List[str] = []

    if asks_for_secret:
        signals.append("query_requests_secret")
        return {
            "request_id": query_id,
            "kind": "query",
            "query": query,
            "route": BLOCKED,
            "reason": "The query itself asks for secret material; the "
                      "assistant refuses and answers only with masked data.",
            "signals": signals,
            "masked_evidence": [],
            "sensitive_found": [],
            "confidence": 0.90,
        }

    if any(d.get("risk") == "high" for d in evidence_sensitive):
        signals.append("evidence_high_risk")
        route, reason, conf = BLOCKED, (
            "Answering would require processing high-risk secret values; "
            "the request is blocked."), 0.88
    elif any(d.get("type") in _NEED_APPROVAL for d in evidence_sensitive):
        signals.append("evidence_needs_approval")
        route, reason, conf = CONFIRM, (
            "Answering touches data that requires explicit confirmation."), 0.82
    else:
        signals.append("evidence_safe")
        route, reason, conf = LOCAL, (
            "The evidence contains no high-risk or approval-required data; "
            "safe to process locally."), 0.72

    return {
        "request_id": query_id,
        "kind": "query",
        "query": query,
        "route": route,
        "reason": reason,
        "signals": signals,
        "masked_evidence": evidence,       # masked excerpts only
        "sensitive_found": evidence_sensitive,
        "confidence": conf,
    }