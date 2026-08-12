import unittest

from kastack.extractor import extract


def item_for(mid, text, sender, ts, category):
    items = extract(mid, text, sender, ts, category)
    return items[0] if items else None


class TestTaskExtraction(unittest.TestCase):
    def test_task_with_deadline(self):
        it = item_for("MSG_0002",
                      "Can you review the privacy checklist before 2026-09-09?",
                      "Ishaan", "2026-09-01 08:37:00", "action_required")
        self.assertEqual(it["type"], "task")
        self.assertEqual(it["title"], "Review the privacy checklist")
        self.assertEqual(it["deadline"], "2026-09-09")
        self.assertEqual(it["time"], None)
        self.assertEqual(it["person"], None)
        self.assertEqual(it["priority"], "medium")
        self.assertEqual(it["source_message_id"], "MSG_0002")

    def test_high_priority_urgent_deadline(self):
        it = item_for("MSG_0007",
                      "For today: Please reply to the client email by "
                      "2026-09-04.", "Ananya", "2026-09-01 11:42:00",
                      "action_required")
        self.assertEqual(it["title"], "Reply to the client email")
        self.assertEqual(it["deadline"], "2026-09-04")
        self.assertEqual(it["priority"], "high")

    def test_dont_forget_with_deadline(self):
        it = item_for("MSG_0010",
                      "Don't forget to pay the electricity bill; deadline is "
                      "2026-09-09.", "Tara", "2026-09-01 13:33:00",
                      "action_required")
        self.assertEqual(it["title"], "Pay the electricity bill")
        self.assertEqual(it["priority"], "high")

    def test_person_detected(self):
        it = item_for("MSG_0056", "Please note: Please call Maya when you are "
                      "free.", "Kabir", "2026-09-02 17:55:00",
                      "action_required")
        self.assertEqual(it["title"], "Call Maya")
        self.assertEqual(it["person"], "Maya")
        self.assertEqual(it["priority"], "low")

    def test_no_date_is_null_not_invented(self):
        it = item_for("MSG_0041",
                      "For today: If possible, review the file before the "
                      "meeting.", "Vikram", "2026-09-02 08:40:00",
                      "action_required")
        self.assertEqual(it["deadline"], None)
        self.assertEqual(it["time"], None)
        self.assertEqual(it["priority"], "low")

    def test_relative_time_is_unresolved(self):
        it = item_for("MSG_0310", "Could you send it soon?", "Aarav",
                      "2026-09-09 06:33:00", "action_required")
        self.assertEqual(it["title"], "Send it")
        self.assertEqual(it["deadline"], None)
        self.assertFalse(it["notes"])

    def test_non_action_messages_produce_nothing(self):
        it = item_for("MSG_0012", "FYI: I will send the login details "
                      "separately.", "Neha", "2026-09-01 14:47:00",
                      "general_information")
        self.assertIsNone(it)


class TestEventExtraction(unittest.TestCase):
    def test_calendar_event(self):
        it = item_for("MSG_0001",
                      "For today: Calendar update: family dinner, 2026-09-19 "
                      "at 10:00, the library.", "Meera",
                      "2026-09-01 08:00:00", "meeting_or_event")
        self.assertEqual(it["type"], "event")
        self.assertEqual(it["title"], "Family dinner")
        self.assertEqual(it["deadline"], "2026-09-19")
        self.assertEqual(it["time"], "10:00")
        self.assertEqual(it["location"], "the library")
        self.assertEqual(it["notes"], [])

    def test_reminder_event(self):
        it = item_for("MSG_0003",
                      "FYI: Reminder: mentor catch-up happens on 2026-09-16 "
                      "at 11:00 in the city clinic.", "Kabir",
                      "2026-09-01 09:14:00", "meeting_or_event")
        self.assertEqual(it["title"], "Mentor catch-up")
        self.assertEqual(it["deadline"], "2026-09-16")
        self.assertEqual(it["time"], "11:00")
        self.assertEqual(it["location"], "the city clinic")

    def test_join_event(self):
        it = item_for("MSG_0036",
                      "Please join the study-group session on 2026-09-13, "
                      "12:00 at Google Meet.", "Maya", "2026-09-02 05:35:00",
                      "meeting_or_event")
        self.assertEqual(it["title"], "Study-group session")
        self.assertEqual(it["location"], "Google Meet")

    def test_availability_event(self):
        it = item_for("MSG_0103",
                      "Important: Are you available for the technical "
                      "interview at 16:00 on 2026-09-05? Location: the main "
                      "office.", "Neha", "2026-09-03 22:54:00",
                      "meeting_or_event")
        self.assertEqual(it["title"], "Technical interview")
        self.assertEqual(it["deadline"], "2026-09-05")
        self.assertEqual(it["time"], "16:00")
        self.assertEqual(it["location"], "the main office")
        self.assertEqual(it["priority"], "high")

    def test_vague_review_event_unresolved(self):
        it = item_for("MSG_0037",
                      "One more thing: The review could be Friday afternoon.",
                      "Meera", "2026-09-02 06:12:00", "meeting_or_event")
        self.assertEqual(it["title"], "Review (tentative)")
        self.assertEqual(it["deadline"], "unresolved")
        self.assertEqual(it["time"], None)
        self.assertEqual(it["location"], None)
        self.assertIn("Relative time phrase", it["notes"][0])
        self.assertEqual(it["priority"], "low")


if __name__ == "__main__":
    unittest.main()