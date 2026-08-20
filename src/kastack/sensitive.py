"""Part 3 - Sensitive information detection and masking.

The detector looks for concrete sensitive values (not just topic words).
A message like *"I will send the login details separately"* contains no
sensitive value and is therefore NOT flagged, while *"Use password
BlueRiver#29 to sign in"* is flagged because a secret value is present.

Every detected message stores only a masked version. Raw values are never
written to logs, outputs, or the web UI.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .common import display_text, mask_value

# (sensitivity_type, risk, recommended_action, regex capturing the value)
# The regexes are deliberately narrow so that only *values* are extracted.
_RULES: List[Dict[str, Any]] = [
    {
        "sensitivity_type": "password",
        "risk": "high",
        "recommended_action": "do_not_store",
        "name": "password",
        "pattern": re.compile(
            r"\b(?:use\s+)?password\s*(?:[:=]|\bis\s+|[-\s])"
            r"([A-Za-z0-9#@_.!*\-]+)",
            re.IGNORECASE,
        ),
        "stopwords": {"is", "to", "for", "the", "and", "or", "with",
                      "your", "my", "new"},
    },
    {
        "sensitivity_type": "one_time_password",
        "risk": "high",
        "recommended_action": "do_not_store",
        "name": "OTP",
        "pattern": re.compile(
            r"\bOTP\s+is\s+([0-9]+(?:-[0-9]+)?)", re.IGNORECASE
        ),
    },
    {
        "sensitivity_type": "bank_account_number",
        "risk": "high",
        "recommended_action": "do_not_send_to_external_service",
        "name": "bank account number",
        "pattern": re.compile(
            r"\bbank\s+account\s+number\s*(?::|is)?\s*([0-9]{6,}(?:-[0-9]+)?)",
            re.IGNORECASE,
        ),
    },
    # L2 variant: "The sample bank account is 001278903456."
    {
        "sensitivity_type": "bank_account_number",
        "risk": "high",
        "recommended_action": "do_not_send_to_external_service",
        "name": "bank account number",
        "pattern": re.compile(
            r"\bbank\s+account\s+is\s+([0-9]{6,}(?:-[0-9]+)?)",
            re.IGNORECASE,
        ),
    },
    {
        "sensitivity_type": "card_number",
        "risk": "high",
        "recommended_action": "do_not_send_to_external_service",
        "name": "card number",
        "pattern": re.compile(
            r"\bcard\s+number\s+is\s+([0-9]{4}(?:\s?[0-9]{4}){2,3}(?:-[0-9]+)?)",
            re.IGNORECASE,
        ),
    },
    {
        "sensitivity_type": "authentication_token",
        "risk": "high",
        "recommended_action": "do_not_store",
        "name": "access token",
        "pattern": re.compile(
            r"\baccess\s+token\s+is\s+([A-Za-z0-9_\-]+)", re.IGNORECASE
        ),
    },
    # L2 variants: "Use access token tok_... for ..." and
    # "Integration token: tok_..." (token values start with 'tok_').
    {
        "sensitivity_type": "authentication_token",
        "risk": "high",
        "recommended_action": "do_not_store",
        "name": "access token",
        "pattern": re.compile(
            r"\b(?:access|integration)\s+token\s*(?::|\bis\b)?\s*"
            r"(tok_[A-Za-z0-9_\-]+)", re.IGNORECASE
        ),
    },
    {
        "sensitivity_type": "recovery_code",
        "risk": "high",
        "recommended_action": "do_not_store",
        "name": "account recovery code",
        "pattern": re.compile(
            r"\brecovery\s+code\s+is\s+([A-Za-z0-9\-]+)", re.IGNORECASE
        ),
    },
    # L2 variant: "Save recovery code REC-L2-88-KQ."
    {
        "sensitivity_type": "recovery_code",
        "risk": "high",
        "recommended_action": "do_not_store",
        "name": "account recovery code",
        "pattern": re.compile(
            r"\brecovery\s+code\s+([A-Za-z0-9]{2,}(?:-[A-Za-z0-9]{2,})+)",
            re.IGNORECASE,
        ),
    },
    {
        "sensitivity_type": "personal_identification_number",
        "risk": "medium",
        "recommended_action": "ask_for_confirmation",
        "name": "identification number",
        "pattern": re.compile(
            r"\bidentification\s+number\s+is\s+([A-Za-z0-9\-]+)", re.IGNORECASE
        ),
    },
    {
        "sensitivity_type": "private_phone_number",
        "risk": "medium",
        "recommended_action": "safe_to_process_locally",
        "name": "phone number",
        "pattern": re.compile(
            r"\bcontact\s+me\s+on\s+([0-9][0-9 ]{6,}(?:-[0-9]+)?)", re.IGNORECASE
        ),
    },
    # L2 variant: "Call me on 91234 56789 after the meeting."
    {
        "sensitivity_type": "private_phone_number",
        "risk": "medium",
        "recommended_action": "safe_to_process_locally",
        "name": "phone number",
        "pattern": re.compile(
            r"\bcall\s+me\s+on\s+([0-9][0-9 ]{6,}(?:-[0-9]+)?)", re.IGNORECASE
        ),
    },
    {
        "sensitivity_type": "private_address",
        "risk": "medium",
        "recommended_action": "safe_to_process_locally",
        "name": "home address",
        "pattern": re.compile(
            r"\bhome\s+address\s+is\s+(.+?)[.!?]?$", re.IGNORECASE
        ),
    },
    # L2 variants: "Please deliver it to 17 River Park Street, Chennai-B."
    # and "Deliver the demo device to 22 Green Park Road, Chennai."
    {
        "sensitivity_type": "private_address",
        "risk": "medium",
        "recommended_action": "safe_to_process_locally",
        "name": "delivery address",
        "pattern": re.compile(
            r"\b(?:deliver|send|ship)\s+(?:it|the\s+[a-z][a-z ]{0,40}?)\s+"
            r"to\s+(.+?(?:street|road|lane|avenue|nagar|colony)"
            r"(?:[,\s-]+[A-Za-z0-9_-]+)*)[.!?]?$",
            re.IGNORECASE,
        ),
    },
    {
        "sensitivity_type": "health_information",
        "risk": "medium",
        "recommended_action": "ask_for_confirmation",
        "name": "health test result",
        "pattern": re.compile(
            r"\btest\s+result\s+(?:says|is|:)\s*(.+?)[.!?]?$", re.IGNORECASE
        ),
    },
    # L2 variant: "My private medical note mentions a thyroid condition."
    {
        "sensitivity_type": "health_information",
        "risk": "medium",
        "recommended_action": "ask_for_confirmation",
        "name": "private medical note",
        "pattern": re.compile(
            r"\bprivate\s+medical\s+note\s+mentions\s+(.+?)[.!?]?$",
            re.IGNORECASE,
        ),
    },
]


def detect_sensitive(text: str) -> List[Dict[str, str]]:
    """Return zero or more detections for a raw message.

    Each detection contains the type, risk, recommended action and the
    captured secret value (never emitted outside this function).

    Detections are de-duplicated by (secret value, type): several rules
    may legitimately match the same value (e.g. 'token is tok_x' matches
    both the strict and the compact token pattern); only the strongest
    (first) match is kept.
    """
    found: List[Dict[str, str]] = []
    seen: set = set()
    for rule in _RULES:
        m = rule["pattern"].search(text)
        if not m:
            continue
        secret = m.group(1).strip()
        if not secret:
            continue
        if rule.get("stopwords") and secret.lower() in rule["stopwords"]:
            continue
        if (secret, rule["sensitivity_type"]) in seen:
            continue
        seen.add((secret, rule["sensitivity_type"]))
        found.append(
            {
                "sensitivity_type": rule["sensitivity_type"],
                "risk": rule["risk"],
                "recommended_action": rule["recommended_action"],
                "secret": secret,
            }
        )
    return found


def mask_message(text: str, secrets: List[str]) -> str:
    """Mask every captured secret inside the raw message text."""
    masked = text
    for secret in secrets:
        masked = masked.replace(secret, mask_value(secret))
    return masked


def masked_form(text: str) -> str:
    """Mask-sensitive copy used for every output field."""
    detections = detect_sensitive(text)
    secrets = [d["secret"] for d in detections]
    return mask_message(text, secrets)


def build_records(message_id: str, text: str) -> List[Dict[str, str]]:
    """Public records (masked only) for Part 3 output."""
    records = []
    detections = detect_sensitive(text)
    if not detections:
        return records
    masked_text = display_text(mask_message(text, [d["secret"] for d in detections]))
    for d in detections:
        records.append(
            {
                "message_id": message_id,
                "sensitivity_type": d["sensitivity_type"],
                "risk": d["risk"],
                "masked_text": masked_text,
                "recommended_action": d["recommended_action"],
            }
        )
    return records