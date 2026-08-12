import unittest

from kastack.classifier import classify


class TestClassification(unittest.TestCase):
    """Explicit expected decisions for curated messages from the dataset."""

    CASES = {
        # (message, sender, expected_category)
        "MSG_0002": ("Can you review the privacy checklist before 2026-09-09?",
                     "Ishaan", "action_required"),
        "MSG_0007": ("For today: Please reply to the client email by 2026-09-04.",
                     "Ananya", "action_required"),
        "MSG_0010": ("Can you help? Don't forget to pay the electricity bill; "
                     "deadline is 2026-09-09.", "Tara", "action_required"),
        "MSG_0017": ("Can you help? I need you to renew the library book by "
                     "2026-09-08.", "Vikram", "action_required"),
        "MSG_0027": ("Please note: Please confirm the interview slot by "
                     "2026-09-05.", "Aarav", "action_required"),
        "MSG_0035": ("For today: Complete the onboarding form is due on "
                     "2026-09-10.", "Rohan", "action_required"),
        "MSG_0001": ("For today: Calendar update: family dinner, 2026-09-19 "
                     "at 10:00, the library.", "Meera", "meeting_or_event"),
        "MSG_0003": ("FYI: Reminder: mentor catch-up happens on 2026-09-16 "
                     "at 11:00 in the city clinic.", "Kabir",
                     "meeting_or_event"),
        "MSG_0011": ("Just checking—Please join the internship orientation "
                     "on 2026-09-18, 13:00 at Conference Room 2.", "Ishaan",
                     "meeting_or_event"),
        "MSG_0023": ("Hi, Calendar update: team stand-up, 2026-09-04 at "
                     "15:00, the college auditorium.", "Rohan",
                     "meeting_or_event"),
        "MSG_0036": ("Please join the study-group session on 2026-09-13, "
                     "12:00 at Google Meet.", "Maya", "meeting_or_event"),
        "MSG_0042": ("For today: The client discussion is scheduled for "
                     "2026-09-12 at 11:00 in Meeting Room A.", "Aarav",
                     "meeting_or_event"),
        "MSG_0103": ("Important: Are you available for the technical "
                     "interview at 16:00 on 2026-09-05? Location: the main "
                     "office.", "Neha", "meeting_or_event"),
        "MSG_0009": ("For my profile, my emergency contact is my brother.",
                     "Meera", "personal_information"),
        "MSG_0016": ("Just checking—Remember that i drink coffee without "
                     "sugar.", "Rohan", "personal_information"),
        "MSG_0022": ("Can you help? Personal note: my favourite language is "
                     "Python.", "Maya", "personal_information"),
        "MSG_0024": ("Just checking—I might prefer evening meetings now.",
                     "Ananya", "personal_information"),
        "MSG_0029": ("Can you help? Just so you know, i prefer receiving "
                     "updates by email.", "Ishaan", "personal_information"),
        "MSG_0004": ("One more thing: The training material is on the portal.",
                     "Aarav", "general_information"),
        "MSG_0006": ("Important: The laptop battery is fully charged.",
                     "Meera", "general_information"),
        "MSG_0012": ("FYI: I will send the login details separately.", "Neha",
                     "general_information"),
        "MSG_0025": ("FYI: The office Wi-Fi will be under maintenance "
                     "tonight.", "Maya", "general_information"),
        "MSG_0026": ("Quick update: The shuttle leaves every thirty minutes.",
                     "Kabir", "general_information"),
        "MSG_0152": ("Hi, The report may be needed tomorrow.", "Rohan",
                     "general_information"),
        "MSG_0014": ("Can you help? Special festival discount on clothing. "
                     "Use code SAVE17.", "Promotions", "promotional"),
        "MSG_0015": ("Please note: Flash sale on laptops starts at 6 PM. Use "
                     "code SAVE23.", "Promotions", "promotional"),
        "MSG_0061": ("Quick update: Get 25% off selected headphones this "
                     "weekend. Use code SAVE30.", "Promotions", "promotional"),
        "MSG_0230": ("Can you help? You may like our new student plan.",
                     "Ishaan", "promotional"),
        # Sensitive messages are provided with their detection flag by the
        # pipeline; the flag must steer the classifier.
    }

    def test_expected_categories(self):
        for mid, (text, sender, expected) in self.CASES.items():
            with self.subTest(mid=mid):
                result = classify(text, sender)
                self.assertEqual(result["category"], expected, msg=mid)

    def test_reason_populated(self):
        result = classify(
            "Please reply to the client email by 2026-09-04.", "Ananya")
        self.assertIn("request verb", result["reason"])
        self.assertIn("2026-09-04", result["reason"])

    def test_sensitive_flag_wins(self):
        base = classify("Use password BlueRiver#29 to sign in.", "Ishaan")
        self.assertEqual(base["category"], "action_required")
        flagged = classify("Use password BlueRiver#29 to sign in.", "Ishaan",
                           sensitive_detected=True)
        self.assertEqual(flagged["category"], "sensitive_information")
        self.assertGreaterEqual(flagged["confidence"], 0.9)

    def test_vague_review_is_uncertain(self):
        result = classify("One more thing: The review could be Friday "
                          "afternoon.", "Meera")
        self.assertEqual(result["category"], "meeting_or_event")
        self.assertTrue(result["uncertain"])
        self.assertLess(result["confidence"], 0.65)

    def test_confidence_in_range(self):
        for mid, (text, sender, _) in self.CASES.items():
            with self.subTest(mid=mid):
                result = classify(text, sender)
                self.assertGreaterEqual(result["confidence"], 0.50)
                self.assertLessEqual(result["confidence"], 0.97)


if __name__ == "__main__":
    unittest.main()