"""Strict handoff contract without clinical content or database access."""
import unittest

from pydantic import ValidationError

from backend.app.schemas.interview_summary import InterviewAssistantSummary


def summary_payload():
    question = dict(id="test_question", text_fa="پرسش آزمون نرم‌افزار",
                    purpose_fa="آزمون قرارداد", answer_type="yes_no",
                    question_version="test-1",
                    provenance={"kind": "design_draft", "reference": "software test"})
    item = dict(question_id="test_question", question=question["text_fa"],
                question_definition=question, state="unknown", value=None,
                unit=None, supplementary_text=None,
                recorded_at="2026-10-19T12:00:00+00:00", source="patient_portal",
                bank_sha256="a" * 64, question_version="test-1",
                provenance=question["provenance"], answer_event_id="test-event")
    return dict(bank_sha256="a" * 64, physician_id="test-physician",
                request_id="test-request", interview_version=1, items=[item],
                missing_question_ids=[], unknown_question_ids=["test_question"],
                declined_question_ids=[], inactive_question_ids=[],
                summary_fa="اطلاعات گزارش‌شده توسط بیمار؛ نیازمند بررسی پزشک.")


class InterviewSummaryTests(unittest.TestCase):
    def test_unknown_and_clinical_status_remain_explicit(self):
        item = InterviewAssistantSummary.model_validate(summary_payload())
        self.assertEqual(item.schema_version, "1.0.0")
        self.assertTrue(item.patient_reported_only)
        self.assertTrue(item.requires_clinician_review)
        self.assertIsNone(item.items[0].value)

    def test_rejects_claimed_diagnosis_probability_or_clinical_authority(self):
        for key, value in (("diagnosis", "claimed"), ("probability", 0.5),
                           ("treatment", "claimed"), ("patient_reported_only", False),
                           ("requires_clinician_review", False)):
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    InterviewAssistantSummary.model_validate({**summary_payload(), key: value})

    def test_rejects_mismatched_provenance_timestamp_and_answer_partition(self):
        for key, value in (("bank_sha256", "b" * 64), ("recorded_at", None),
                           ("recorded_at", "2026-10-19T12:00:00"),
                           ("question_version", "wrong-version"), ("value", "no")):
            with self.subTest(key=key, value=value):
                data = summary_payload()
                data["items"][0][key] = value
                with self.assertRaises(ValidationError):
                    InterviewAssistantSummary.model_validate(data)
        for key, value in (("missing_question_ids", ["test_question"]),
                           ("inactive_question_ids", ["test_question"]),
                           ("unknown_question_ids", [])):
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    InterviewAssistantSummary.model_validate({**summary_payload(), key: value})

    def test_missing_historical_timestamp_is_honestly_marked(self):
        data = summary_payload()
        data["items"][0].update(source="legacy_patient_portal", recorded_at=None)
        parsed = InterviewAssistantSummary.model_validate(data)
        self.assertIsNone(parsed.items[0].recorded_at)


if __name__ == "__main__":
    unittest.main()
