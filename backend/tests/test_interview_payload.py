"""Transport semantics independent of medical question content."""
import unittest

from pydantic import ValidationError

from backend.app.schemas.patient_portal import PortalAnswerCreate


class InterviewPayloadTests(unittest.TestCase):
    def payload(self, **updates):
        return dict(request_key="payload-test-1", expected_version=0,
                    question_id="synthetic_measurement", state="answered",
                    value=0, unit="test-unit", **updates)

    def test_zero_keeps_numeric_type(self):
        for value in (0, 0.0, 2.5):
            with self.subTest(value=value):
                data = self.payload()
                data["value"] = value
                parsed = PortalAnswerCreate.model_validate(data)
                self.assertEqual(parsed.value, value)
                self.assertIs(type(parsed.value), type(value))

    def test_rejects_boolean_nonfinite_and_structured_values(self):
        for value in (True, False, float("nan"), float("inf"), -float("inf"), [], {}):
            with self.subTest(value=value):
                data = self.payload()
                data["value"] = value
                with self.assertRaises(ValidationError):
                    PortalAnswerCreate.model_validate(data)

    def test_unknown_and_declined_are_not_values(self):
        for state in ("unknown", "declined"):
            data = self.payload()
            data.update(state=state, value=None, unit=None,
                        supplementary_text="توضیح اختیاری بیمار")
            parsed = PortalAnswerCreate.model_validate(data)
            self.assertIsNone(parsed.value)
            self.assertEqual(parsed.state, state)
            for key, value in (("value", 0), ("unit", "test-unit")):
                bad = {**data, key: value}
                with self.assertRaises(ValidationError):
                    PortalAnswerCreate.model_validate(bad)

    def test_answered_requires_a_value_and_rejects_claimed_server_metadata(self):
        data = self.payload()
        data["value"] = None
        with self.assertRaises(ValidationError):
            PortalAnswerCreate.model_validate(data)
        for key in ("recorded_at", "source", "bank_sha256", "clinician_confirmed"):
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    PortalAnswerCreate.model_validate({**self.payload(), key: "claimed"})

    def test_legacy_text_is_not_coerced_to_number(self):
        data = self.payload()
        data.update(value="0", unit=None)
        parsed = PortalAnswerCreate.model_validate(data)
        self.assertIsInstance(parsed.value, str)
        # The bank evaluator, which knows the question type, rejects this for
        # number questions. Text questions retain their existing text contract.


if __name__ == "__main__":
    unittest.main()
