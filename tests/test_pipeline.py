import json
import re
import unittest
from pathlib import Path

from kastack.pipeline import (
    load_mandatory_ids,
    load_messages,
    run_pipeline,
    write_outputs,
)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "outputs"

SECRET_PATTERNS = [
    r"BlueRiver#\d+", r"482193(-|$)", r"006418220145", r"tok_demo_A8K29Q",
    r"RC-88-KL-19", r"ID-7842-XY", r"98765\s*43210", r"4111\s*1111",
    r"42 Lake View Road",
]


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.messages = load_messages(str(DATA / "messages.csv"))
        cls.mandatory = load_mandatory_ids(
            str(DATA / "mandatory_demo_ids.csv"))
        assert len(cls.messages) == 900
        assert len(cls.mandatory) == 15
        cls.processed = run_pipeline(cls.messages, cls.mandatory)
        cls.stats = write_outputs(cls.processed, str(OUT), cls.mandatory)

    def test_count(self):
        self.assertEqual(len(self.processed["classification"]), 900)

    def test_chronological_order(self):
        stamps = [c["timestamp"] for c in self.processed["classification"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_all_six_categories_present(self):
        cats = {c["category"] for c in self.processed["classification"]}
        self.assertEqual(cats, {
            "action_required", "meeting_or_event", "personal_information",
            "general_information", "promotional", "sensitive_information",
        })

    def test_mandatory_ids_all_present(self):
        found = {m["message_id"] for m in self.processed["mandatory"]}
        self.assertEqual(found, set(self.mandatory))
        self.assertEqual(self.stats["mandatory_missing"], [])

    def test_every_mandatory_row_has_all_three_parts(self):
        for row in self.processed["mandatory"]:
            self.assertIn("classification", row)
            self.assertIn("items", row)
            self.assertIn("sensitive", row)

    def test_sensitive_consistency(self):
        sensitive_ids = {c["message_id"] for c in
                         self.processed["classification"]
                         if c["category"] == "sensitive_information"}
        detected_ids = {r["message_id"] for r in
                        self.processed["sensitive"]}
        self.assertEqual(sensitive_ids, detected_ids)

    def test_no_secret_values_in_output_files(self):
        for name in ("classification.json", "tasks_events.json",
                     "sensitive_detections.json", "mandatory_results.json",
                     "summary.json"):
            text = (OUT / name).read_text(encoding="utf-8")
            for pattern in SECRET_PATTERNS:
                self.assertNotRegex(text, pattern,
                                    msg=f"{name} leaked {pattern}")

    def test_no_secret_values_in_masked_rows(self):
        for c in self.processed["classification"]:
            for pattern in SECRET_PATTERNS:
                self.assertNotRegex(c["message_masked"], pattern,
                                    msg=f"{c['message_id']} leaked {pattern}")

    def test_tasks_and_events_extracted(self):
        types = [i["type"] for i in self.processed["tasks_events"]]
        self.assertGreater(types.count("task"), 200)
        self.assertGreater(types.count("event"), 150)
        for item in self.processed["tasks_events"]:
            self.assertTrue(
                item["item_id"].startswith("TASK_") or
                item["item_id"].startswith("EVENT_"))

    def test_sensitive_records_masked(self):
        for r in self.processed["sensitive"]:
            for pattern in SECRET_PATTERNS:
                self.assertNotRegex(r["masked_text"], pattern)

    def test_pipeline_deterministic(self):
        again = run_pipeline(self.messages[:50], self.mandatory)
        first = self.processed["classification"][:50]
        for a, b in zip(first, again["classification"]):
            self.assertEqual(a["category"], b["category"])
            self.assertEqual(a["confidence"], b["confidence"])


if __name__ == "__main__":
    unittest.main()