"""Unit tests for the L2 extension (priority, grouping, retrieval,
privacy routing and the intelligent assistant).

All functional tests are hermetic: they use small synthetic message sets
so the suite never depends on the private L2 datasets. A final smoke test
scans the *generated* outputs for raw secret values and is skipped when
the pipeline has not been run yet.
"""

import json
import re
import unittest
from pathlib import Path

from kastack.l2_assistant import Assistant
from kastack.l2_core import (
    ItemRegistry, canonical_phrase, canonical_quality,
)
from kastack.l2_index import SparseIndex, naive_search, tokenize
from kastack.l2_pipeline import L2Context, process_batch
from kastack.l2_priority import (
    CRITICAL, HIGH, LOW, UNCLEAR, detect_status_action, evaluate,
)
from kastack.l2_routing import (
    BLOCKED, CONFIRM, LOCAL, decide_message, decide_query,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
SRC = ROOT / "src"


def rows(*pairs):
    """Turn (message_id, timestamp, sender, text) tuples into CSV rows."""
    out = []
    for i, (mid, ts, sender, text) in enumerate(pairs):
        out.append({
            "message_id": mid,
            "timestamp": ts,
            "sender": sender,
            "message": text,
        })
    return out


def run(ctx, batch):
    process_batch(ctx, batch, "corpus", set())
    return ctx


def fresh_ctx() -> L2Context:
    return L2Context()


class TestMovingForward(unittest.TestCase):
    """Regression: hyphenated dates and 'Confirmed: ...' phrasing must not
    be mangled by the status-detector normalisation."""

    def test_iso_and_hyphen_survive_normalisation(self):
        low = re.sub(r"[^\w\s\-:]+", " ", "Moved to 2026-10-07 17:30!".lower())
        self.assertEqual(low, "moved to 2026-10-07 17:30 ")

    def test_confirmed_colon_is_not_auto_completed(self):
        # "Confirmed: email the signed document" is an instruction, not a
        # completion statement (needs "has been completed" too).
        self.assertEqual(
            detect_status_action("Confirmed: email the signed document."),
            "pending")

    def test_status_actions(self):
        self.assertEqual(
            detect_status_action("The event has been cancelled."), "cancelled")
        self.assertEqual(
            detect_status_action("It has been completed successfully."),
            "completed")
        self.assertEqual(
            detect_status_action("The meeting has moved to 2026-10-09."),
            "rescheduled")
        self.assertEqual(
            detect_status_action("Wait for the official update."), "unclear")
        self.assertEqual(
            detect_status_action("It may no longer be urgent."), "not_urgent")


class TestCanonicalMatching(unittest.TestCase):
    def test_canonical_phrase_normalises(self):
        self.assertEqual(canonical_phrase("  Weekly   Report! "),
                         "weekly report")

    def test_quality_scoring(self):
        self.assertGreater(
            canonical_quality("weekly report update"), 0.7)
        self.assertLess(
            canonical_quality("nonsense"), 0.75)

    def test_fuzzy_but_not_cross_topic(self):
        reg = ItemRegistry()
        reg.seed("weekly report", "task", "Submit the weekly report", "T_1")
        key, score, how = reg.match_key("project report", "task")
        # token overlap is tiny: a different thread must NOT win
        self.assertIsNone(key)


class TestJunkTopicGuard(unittest.TestCase):
    """Regression: status-marker words ("has", "is", "was") used to become
    junk topic keys. The new-item guard refuses < 2 content tokens."""

    def test_stopword_lead_in_does_not_create_item(self):
        ctx = run(fresh_ctx(), rows(
            ("J1", "2026-09-01 08:00:00", "A",
             "The building entrance has moved to the north wing."),
        ))
        keys = {k for k in ctx.registry.seed_keys}
        self.assertNotIn("has", keys)
        self.assertNotIn("is", keys)
        self.assertNotIn("was", keys)
        # the relocation is captured as a real (event) topic, never as a
        # stopword key
        self.assertEqual(list(keys), ["building entrance"])
        self.assertEqual(len(ctx.registry.items), 1)

    def test_real_update_still_creates_item(self):
        ctx = run(fresh_ctx(), rows(
            ("J2", "2026-09-01 08:00:00", "A",
             "Please renew the library book by 2026-10-03."),
        ))
        self.assertEqual(len(ctx.registry.items), 1)
        rec = list(ctx.registry.items.values())[0]
        self.assertEqual("renew the library book", canonical_phrase(rec.title))


class TestRegistryLifecycle(unittest.TestCase):
    def setUp(self):
        self.ctx = run(fresh_ctx(), rows(
            ("R1", "2026-09-01 08:00:00", "A",
             "Please prepare the weekly report by 2026-10-05."),
            ("R2", "2026-09-02 09:00:00", "A",
             "Follow-up: any update on the weekly report?"),
        ))

    def test_single_thread(self):
        rec = list(self.ctx.registry.items.values())[0]
        self.assertEqual(rec.message_ids, ["R1", "R2"])
        self.assertEqual(rec.followup_count, 1)

    def test_terminal_status_closed(self):
        ctx = run(fresh_ctx(), rows(
            ("R3", "2026-09-01 08:00:00", "A",
             "Please fix the tracking sheet by 2026-10-05."),
            ("R4", "2026-10-06 09:00:00", "A",
             "Confirmed: Fix the tracking sheet has been completed "
             "successfully."),
        ))
        rec = list(ctx.registry.items.values())[0]
        self.assertEqual(rec.status, "completed")
        self.assertEqual(rec.message_ids, ["R3", "R4"])


class TestPriorityEngine(unittest.TestCase):
    def _item(self, deadline="2026-10-05"):
        ctx = run(fresh_ctx(), rows(
            ("P1", "2026-09-01 08:00:00", "Auth",
             f"Please amend the charter; it is due on {deadline}."),
        ))
        rec = list(ctx.registry.items.values())[0]
        self.assertEqual(rec.latest_deadline, deadline)
        return rec

    @staticmethod
    def _eval(rec, mid, ts, text, status="pending"):
        return evaluate(rec, mid, ts, "", "action_required",
                        text, status, False)

    def test_due_today_is_high(self):
        rec = self._item(deadline="2026-09-01")
        d = self._eval(rec, "P2", "2026-09-01 08:00:00", "no new info")
        self.assertEqual(d["priority"], HIGH)

    def test_overdue_is_critical(self):
        rec = self._item(deadline="2026-09-01")
        d = self._eval(rec, "P2", "2026-10-02 08:00:00", "no new info")
        self.assertEqual(d["priority"], CRITICAL)

    def test_terminal_events_downgrade_to_low(self):
        rec = self._item()
        rec.status = "completed"
        d = self._eval(rec, "P2", "2026-09-10 08:00:00",
                       "It has been completed successfully.", "completed")
        self.assertEqual(d["priority"], LOW)
        self.assertIn("no_action_needed", d["signals"])

    def test_unclear_status_keeps_existing_priority(self):
        rec = self._item()
        rec.priority = CRITICAL
        d = self._eval(rec, "P2", "2026-09-10 08:00:00",
                       "Wait for the official update.", "unclear")
        self.assertEqual(d["priority"], CRITICAL)
        self.assertIn("uncertainty_keeps_priority", d["signals"])

    def test_unlinked_messages_emit_no_decision(self):
        self.assertIsNone(evaluate(None, "P9", "2026-09-10 08:00:00",
                                   "", "general_information",
                                   "Just a note.", "pending", False))


class TestPrivacyRouting(unittest.TestCase):
    def test_high_risk_blocked(self):
        d = decide_message("S1", "Your OTP is 864219.", "2026-10-04 10:00:00",
                           "A")
        self.assertEqual(d["route"], BLOCKED)
        self.assertNotIn("864219", d["masked_evidence"])

    def test_address_local(self):
        d = decide_message(
            "S2", "Deliver it to 17 River Park Street, Chennai-B.",
            "2026-10-04 10:00:00", "A")
        self.assertEqual(d["route"], LOCAL)
        self.assertNotIn("River Park", d["masked_evidence"])

    def test_medical_ask_confirmation(self):
        d = decide_message(
            "S3", "My private medical note mentions a thyroid condition.",
            "2026-10-04 10:00:00", "A")
        self.assertEqual(d["route"], CONFIRM)

    def test_ambiguous_ask_confirmation(self):
        d = decide_message("S4", "Wait for the official update.",
                           "2026-10-04 10:00:00", "A")
        self.assertEqual(d["route"], CONFIRM)
        self.assertIn("status_ambiguous", d["signals"])

    def test_query_routing_blocked(self):
        d = decide_query("Q1", "what is my bank account number",
                         ["MSG_0001"], [])
        self.assertEqual(d["route"], BLOCKED)


class TestIndexEquivalence(unittest.TestCase):
    DOCS = [
        {"id": "A", "kind": "message",
         "text": "The weekly report is due on Friday."},
        {"id": "B", "kind": "message",
         "text": "Family dinner at the library at 10:00."},
        {"id": "C", "kind": "message",
         "text": "Mentor catch-up has been moved to Monday."},
        {"id": "D", "kind": "item",
         "text": "Submit the weekly report (task)."},
    ]

    def test_tokenize_is_deterministic(self):
        self.assertEqual(tokenize("Weekly Report!"),
                         tokenize("Weekly Report!"))
        self.assertIn("weekly", tokenize("Weekly Report!"))

    def test_naive_and_index_agree_on_top1(self):
        index = SparseIndex(self.DOCS).build()
        for q in ["weekly report", "family dinner", "mentor catch-up"]:
            naive = naive_search(self.DOCS, q, k=3)
            got = index.query(q, k=3)
            self.assertEqual([h[0] for h in naive][:1],
                             [h[0] for h in got][:1], msg=q)

    def test_serialize_round_trip(self):
        index = SparseIndex(self.DOCS).build()
        data = index.serialize()
        self.assertEqual(len(data["doc_ids"]), 4)
        rebuilt = SparseIndex.from_data(data)
        # the short item doc "Submit the weekly report (task)" has the
        # highest cosine for "weekly report"
        self.assertEqual(rebuilt.query("weekly report", k=1)[0][0], "D")


class TestAssistant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # DEMO_*-prefixed ids are the assistant's demo scope (same
        # convention as the real demo batch messages).
        cls.ctx = run(fresh_ctx(), rows(
            ("DEMO_001", "2026-09-20 08:00:00", "Auth",
             "Please prepare the audit deck; it is due on 2026-10-01."),
            ("DEMO_002", "2026-10-02 08:00:00", "Auth",
             "Any update on the audit deck?"),
            ("DEMO_003", "2026-09-20 09:00:00", "A",
             "Team lunch is scheduled for 2026-11-01 at 13:00."),
            ("DEMO_004", "2026-10-15 10:00:00", "A",
             "The team lunch has been moved to 2026-11-05 13:00."),
        ))
        cls.assistant = Assistant(cls.ctx, demo_ids={"DEMO_001", "DEMO_002",
                                                     "DEMO_003", "DEMO_004"})

    def test_became_critical_lists_urgent_item(self):
        a = self.assistant.answer(
            "Which existing task became critical in the demo data?", "DQ")
        self.assertEqual(a["intent"], "became_critical")
        self.assertIn("audit deck", a["final_answer"])
        self.assertIn("DEMO_002", a["supporting_message_ids"])

    def test_rescheduled_lists_moved_event(self):
        a = self.assistant.answer("Which meetings were rescheduled?", "DQ")
        self.assertEqual(a["intent"], "rescheduled")
        self.assertIn("team lunch", a["final_answer"].lower())

    def test_honest_fallback_when_no_evidence(self):
        a = self.assistant.answer("What is the status of the film shoot?",
                                  "DQ")
        self.assertIsInstance(a["final_answer"], str)
        self.assertIsNotNone(a["reason"])


@unittest.skipUnless(
    (OUT / "l2_web_state.json").exists(),
    "run_l2 first: L2 outputs not generated yet")
class TestOutputLeakScan(unittest.TestCase):
    """The generated outputs must never contain a raw secret value.
    Only the *labels* (e.g. "recovery code") or the type names may appear."""

    SECRET_PATTERNS = [
        r"006418220145",        # bank account (L1 corpus)
        r"17 River Park",       # delivery address
        r"22 Green Park",       # demo delivery address
        r"EdgeDemo#771",        # demo password
        r"\b864219\b",          # demo OTP
        r"tok_demo_L2_91XZ",    # demo token
        r"RC-\d{2}-[A-Z]{2}-\d{2}",  # recovery codes
        r"Blood\s*group",       # demo medical attachment
    ]

    def test_no_raw_secrets_in_outputs(self):
        leaks = []
        for path in sorted(OUT.glob("*.json")):
            with open(path, encoding="utf-8") as fh:
                for pat in self.SECRET_PATTERNS:
                    m = re.search(pat, fh.read(), flags=re.IGNORECASE)
                    if m:
                        leaks.append((path.name, pat, m.group(0)))
        self.assertTrue(any(OUT.glob("*.json")))
        self.assertEqual(leaks, [])

    def test_masked_titles_never_hold_secrets(self):
        items = json.loads(
            (OUT / "l2_items.json").read_text(encoding="utf-8"))
        joint = " | ".join(it["title"] for it in items)
        for pat in self.SECRET_PATTERNS:
            self.assertIsNone(re.search(pat, joint, flags=re.IGNORECASE))


if __name__ == "__main__":
    unittest.main(verbosity=2)