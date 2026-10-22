"""Offline review-document boundaries; no application or database imports."""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from backend.tools.review_knee_draft import (
    DEFAULT_DRAFT,
    MAX_DRAFT_BYTES,
    load_draft,
    main,
    render_html,
    validate_draft,
)


class KneeReviewDraftTests(unittest.TestCase):
    def setUp(self):
        self.draft = load_draft(DEFAULT_DRAFT)

    def test_retained_review_preserves_inactive_unknown_provenance(self):
        report = validate_draft(self.draft)
        self.assertEqual(report.errors, [])
        self.assertEqual((report.stage_count, report.node_count), (9, 26))
        self.assertFalse(report.runtime_enabled)
        self.assertFalse(report.clinically_validated)
        self.assertEqual(self.draft["original_artifact"]["mapping_to_original"], "unknown")
        for node in self.draft["nodes"]:
            self.assertEqual(node["status"], "draft")
            self.assertFalse(node["runtime_enabled"])
            for key in ("clinical_question", "answer_schema", "display_condition", "medical_rule"):
                self.assertIsNone(node[key])

    def test_activation_and_approval_claims_are_rejected(self):
        for key in ("runtime_enabled", "registry_imported", "clinically_validated"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.draft)
                changed[key] = True
                self.assertFalse(validate_draft(changed).ok)
        for field, value in (("status", "approved"), ("runtime_enabled", True)):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.draft)
                changed["nodes"][0][field] = value
                self.assertFalse(validate_draft(changed).ok)

    def test_actual_questions_conditions_or_rules_require_a_different_review(self):
        for key, value in (
            ("clinical_question", "Unreviewed clinical question"),
            ("answer_schema", {"type": "number", "minimum": 0}),
            ("display_condition", {"pain_score": 5}),
            ("medical_rule", {"action": "select_treatment"}),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.draft)
                changed["nodes"][0][key] = value
                self.assertFalse(validate_draft(changed).ok)
                with self.assertRaises(ValueError):
                    render_html(changed)

    def test_original_recovery_and_unverified_source_details_cannot_be_claimed(self):
        changed = copy.deepcopy(self.draft)
        changed["original_artifact"]["availability"] = "recovered"
        self.assertFalse(validate_draft(changed).ok)
        for key, value in (("page", "17"), ("section", "Recommendations"), ("source_version", "verified-2024")):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.draft)
                changed["references"][0][key] = value
                self.assertFalse(validate_draft(changed).ok)

    def test_stage_graph_requires_each_concept_once(self):
        changed = copy.deepcopy(self.draft)
        changed["stages"][1]["node_ids"].append("KNEE-R01")
        self.assertFalse(validate_draft(changed).ok)
        changed = copy.deepcopy(self.draft)
        changed["stages"][0]["node_ids"].pop()
        self.assertFalse(validate_draft(changed).ok)
        changed = copy.deepcopy(self.draft)
        changed["nodes"][1]["id"] = "KNEE-R01"
        self.assertFalse(validate_draft(changed).ok)

    def test_parallel_review_and_required_limits_cannot_disappear(self):
        changed = copy.deepcopy(self.draft)
        changed["parallel_candidate_node_ids"] = ["KNEE-R09"]
        self.assertFalse(validate_draft(changed).ok)
        changed = copy.deepcopy(self.draft)
        changed["constraints"].pop()
        self.assertFalse(validate_draft(changed).ok)
        changed = copy.deepcopy(self.draft)
        changed["constraints"][0]["runtime_enabled"] = True
        self.assertFalse(validate_draft(changed).ok)

    def test_unknown_references_and_unsafe_urls_are_rejected(self):
        changed = copy.deepcopy(self.draft)
        changed["nodes"][0]["candidate_reference_ids"] = ["invented-source"]
        self.assertFalse(validate_draft(changed).ok)
        for url in ("javascript:alert(1)", "http://example.com", "https://user:secret@example.com"):
            with self.subTest(url=url):
                changed = copy.deepcopy(self.draft)
                changed["references"][0]["url"] = url
                self.assertFalse(validate_draft(changed).ok)

    def test_extra_fields_and_malformed_containers_fail_closed(self):
        for location in ("root", "node", "reference"):
            with self.subTest(location=location):
                changed = copy.deepcopy(self.draft)
                target = changed if location == "root" else changed["nodes" if location == "node" else "references"][0]
                target["approved"] = True
                self.assertFalse(validate_draft(changed).ok)
        for key in ("nodes", "stages", "constraints", "references", "scope", "provenance"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.draft)
                changed[key] = None
                self.assertFalse(validate_draft(changed).ok)
        self.assertFalse(validate_draft([]).ok)

    def test_render_is_persian_offline_and_escapes_content(self):
        self.draft["nodes"][0]["title_fa"] = '<script src="https://example.com/evil.js">x</script>'
        rendered = render_html(self.draft)
        self.assertIn('lang="fa" dir="rtl"', rendered)
        self.assertIn("&lt;script", rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<iframe", rendered)
        self.assertNotIn("<link", rendered)
        self.assertIn("Content-Security-Policy", rendered)
        self.assertIn("بسته اصلی ۲۶گرهی در این محیط موجود نیست", rendered)
        self.assertEqual(rendered.count('<p class="pending">'), 26)

    def test_json_duplicate_keys_nonfinite_and_oversize_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "draft.json"
            for raw in ('{"status":"draft","status":"approved"}', '{"value":NaN}'):
                with self.subTest(raw=raw):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_draft(path)
            path.write_bytes(b" " * (MAX_DRAFT_BYTES + 1))
            with self.assertRaises(ValueError):
                load_draft(path)

    def test_cli_renders_a_review_with_no_input_mutation(self):
        original = DEFAULT_DRAFT.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "review.html"
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = main(["--html", str(output), "--format", "json"])
            report = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report["ok"])
            self.assertFalse(report["runtime_enabled"])
            self.assertTrue(output.exists())
            self.assertEqual(DEFAULT_DRAFT.read_bytes(), original)

    def test_cli_invalid_input_creates_no_output_and_same_input_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            output = Path(directory) / "review.html"
            source.write_text("not-json", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--input", str(source), "--html", str(output)]), 1)
            self.assertFalse(output.exists())
            source = Path(directory) / "source.html"
            source.write_text(json.dumps(self.draft), encoding="utf-8")
            before = source.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--input", str(source), "--html", str(source)]), 1)
            self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
