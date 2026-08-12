import unittest

from kastack.sensitive import build_records, detect_sensitive, mask_message


class TestSensitiveDetection(unittest.TestCase):
    CASES = [
        ("Use password BlueRiver#29 to sign in to the test account.",
         "password", "high", "do_not_store"),
        ("Your OTP is 482193-50. It expires in 10 minutes.",
         "one_time_password", "high", "do_not_store"),
        ("Please note my bank account number 006418220145-38.",
         "bank_account_number", "high", "do_not_send_to_external_service"),
        ("Hi, My card number is 4111 1111 1111 1111-92.",
         "card_number", "high", "do_not_send_to_external_service"),
        ("The temporary access token is tok_demo_A8K29Q-53.",
         "authentication_token", "high", "do_not_store"),
        ("My account recovery code is RC-88-KL-19-59.",
         "recovery_code", "high", "do_not_store"),
        ("One more thing: My identification number is ID-7842-XY-94.",
         "personal_identification_number", "medium", "ask_for_confirmation"),
        ("Hi, My home address is 42 Lake View Road, Chennai-45.",
         "private_address", "medium", "safe_to_process_locally"),
        ("You can contact me on 98765 43210-86.",
         "private_phone_number", "medium", "safe_to_process_locally"),
        ("My recent test result says vitamin D deficiency-97.",
         "health_information", "medium", "ask_for_confirmation"),
    ]

    def test_types_risks_actions(self):
        for text, expected_type, expected_risk, expected_action in self.CASES:
            with self.subTest(text=text[:40]):
                dets = detect_sensitive(text)
                self.assertEqual(len(dets), 1)
                self.assertEqual(dets[0]["sensitivity_type"], expected_type)
                self.assertEqual(dets[0]["risk"], expected_risk)
                self.assertEqual(dets[0]["recommended_action"],
                                 expected_action)

    def test_no_value_means_not_sensitive(self):
        self.assertEqual(
            detect_sensitive("FYI: I will send the login details separately."),
            [])
        self.assertEqual(
            detect_sensitive("For my profile, my emergency contact is my "
                             "brother."),
            [])
        self.assertEqual(
            detect_sensitive("The webinar recording is now available."), [])

    def test_mask_never_leaks_secret(self):
        for text, *_ in self.CASES:
            with self.subTest(text=text[:40]):
                dets = detect_sensitive(text)
                masked = mask_message(text, [d["secret"] for d in dets])
                for d in dets:
                    self.assertNotIn(d["secret"], masked)
                self.assertNotEqual(masked, text)

    def test_records_only_masked(self):
        for text, expected_type, *_ in self.CASES:
            with self.subTest(text=text[:40]):
                records = build_records("MSG_T", text)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["sensitivity_type"],
                                 expected_type)
                self.assertNotIn(text, records[0]["masked_text"])


if __name__ == "__main__":
    unittest.main()