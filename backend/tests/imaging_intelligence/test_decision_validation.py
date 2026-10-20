"""Synthetic-only contracts. Runnable with stdlib unittest, without app startup."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import unittest

from backend.app.decision_intelligence import (
    ClinicalInput,
    EvaluationRequirements,
    FindingInput,
    FindingProvenance,
    ImagingInput,
    RuleBasedDecisionAdapter,
    ValidationRequest,
)


def reference(symbol: str) -> str:
    # These are synthetic opaque references, not references to patient records.
    return "hmac-sha256:" + hashlib.sha256(symbol.encode("ascii")).hexdigest()


def complete_imaging() -> ImagingInput:
    return ImagingInput(
        metadata_status="valid", metadata_sha256="a" * 64,
        modality="MR", body_region="KNEE", laterality="L",
        study_reference=reference("study"), series_reference=reference("series"),
        instance_reference=reference("instance"),
        technical_fields=("rows", "columns", "pixel_spacing"),
    )


def reviewed_finding() -> FindingInput:
    imaging = complete_imaging()
    return FindingInput(
        finding_reference=reference("finding"), finding_code="synthetic_observation",
        review_status="verified", provenance=FindingProvenance(
            source_instance_reference=imaging.instance_reference,
            source_metadata_sha256=imaging.metadata_sha256,
            source_metadata_schema_version=imaging.metadata_schema_version,
            review_record_reference=reference("review"),
            review_policy_version="finding-review-v1",
        ),
    )


def complete_request() -> ValidationRequest:
    return ValidationRequest(
        clinical=ClinicalInput(
            available_fields=("assessment_context", "clinical_review"),
            body_region="KNEE", laterality="L",
        ),
        imaging=complete_imaging(), findings=(reviewed_finding(),),
    )


class DecisionValidationTests(unittest.TestCase):
    def setUp(self):
        self.adapter = RuleBasedDecisionAdapter()

    def codes(self, result, rule_id):
        return next(trace.codes for trace in result.traces if trace.rule_id == rule_id)

    def test_complete_inputs_are_data_ready_only_and_every_rule_is_traced(self):
        result = self.adapter.evaluate(complete_request())
        self.assertEqual(result.status, "data_ready")
        self.assertEqual(result.scope, "data_validation_only")
        self.assertIs(result.is_diagnosis, False)
        self.assertIs(result.is_treatment_recommendation, False)
        self.assertEqual(result.eligible_finding_references, (reference("finding"),))
        self.assertEqual(result.blocked_finding_references, ())
        self.assertEqual(result.next_steps, ())
        self.assertEqual(len(result.traces), 7)
        self.assertTrue(all(trace.rule_version == "1.0.0" for trace in result.traces))
        self.assertTrue(all(trace.outcome == "passed" for trace in result.traces))
        self.assertEqual(result.adapter_id, "4b.data-validation.rules")

    def test_missing_clinical_and_imaging_data_describe_completion_steps(self):
        result = self.adapter.evaluate(ValidationRequest(clinical=ClinicalInput()))
        self.assertEqual(result.status, "needs_data")
        self.assertEqual(result.missing_clinical_fields, ("assessment_context", "clinical_review"))
        self.assertEqual(result.missing_imaging_fields, ("imaging_metadata",))
        self.assertEqual(result.next_steps, (
            "complete_required_clinical_data", "resolve_required_imaging_metadata"
        ))
        self.assertFalse(any("order" in step or "diagnos" in step for step in result.next_steps))

    def test_required_fields_are_configurable_and_optional_imaging_is_not_requested(self):
        requirements = EvaluationRequirements(
            required_clinical_fields=("symptom_history",), require_imaging=False
        )
        request = ValidationRequest(clinical=ClinicalInput(available_fields=("symptom_history",)))
        result = RuleBasedDecisionAdapter(requirements).evaluate(request)
        self.assertEqual(result.status, "data_ready")
        self.assertEqual(result.next_steps, ())
        self.assertEqual(next(t.outcome for t in result.traces
                              if t.rule_id == "imaging_completeness"), "not_applicable")

    def test_technical_fields_and_anatomic_context_can_be_required_explicitly(self):
        requirements = EvaluationRequirements(
            required_technical_fields=("rows", "pixel_spacing", "slice_thickness"),
            required_imaging_fields=("modality", "body_region", "laterality"),
        )
        request = replace(complete_request(), imaging=replace(complete_imaging(), body_region=None))
        result = RuleBasedDecisionAdapter(requirements).evaluate(request)
        self.assertEqual(result.status, "needs_data")
        self.assertEqual(result.missing_imaging_fields, ("body_region", "slice_thickness"))

    def test_incomplete_invalid_or_issue_bearing_metadata_cannot_be_ready(self):
        for status in ("incomplete", "invalid"):
            with self.subTest(status=status):
                request = replace(complete_request(), imaging=replace(complete_imaging(), metadata_status=status))
                result = self.adapter.evaluate(request)
                self.assertEqual(result.status, "needs_data")
                self.assertEqual(result.eligible_finding_references, ())
                self.assertIn("imaging_metadata_not_valid", self.codes(result, "imaging_completeness"))
        request = replace(complete_request(), imaging=replace(complete_imaging(), issue_codes=("missing_field",)))
        result = self.adapter.evaluate(request)
        self.assertEqual(result.status, "needs_data")
        self.assertIn("unresolved_imaging_metadata_issues", self.codes(result, "imaging_completeness"))

    def test_modality_body_region_and_laterality_mismatches_are_reported(self):
        requirements = EvaluationRequirements(
            expected_modality="CT", expected_body_region="HIP", expected_laterality="R"
        )
        request = replace(complete_request(), clinical=ClinicalInput(
            available_fields=("assessment_context", "clinical_review"), body_region="HIP", laterality="R"
        ))
        result = RuleBasedDecisionAdapter(requirements).evaluate(request)
        self.assertEqual(result.status, "needs_data")
        self.assertEqual(set(self.codes(result, "context_consistency")), {
            "modality_does_not_match_requirement", "body_region_does_not_match_requirement",
            "laterality_does_not_match_requirement", "clinical_imaging_body_region_mismatch",
            "clinical_imaging_laterality_mismatch",
        })
        self.assertEqual(result.eligible_finding_references, ())
        self.assertIn("reconcile_context_metadata", result.next_steps)

    def test_unverified_and_rejected_findings_never_become_eligible(self):
        for review_status in ("unverified", "rejected"):
            with self.subTest(review_status=review_status):
                finding = replace(reviewed_finding(), review_status=review_status)
                result = self.adapter.evaluate(replace(complete_request(), findings=(finding,)))
                self.assertEqual(result.status, "needs_data")
                self.assertEqual(result.eligible_finding_references, ())
                self.assertEqual(result.blocked_finding_references, (reference("finding"),))
                self.assertIn("finding_not_verified", self.codes(result, "finding_verification"))

    def test_mixed_finding_results_trace_each_reference_without_echoing_codes(self):
        good = reviewed_finding()
        unverified = replace(good, finding_reference=reference("unverified"), review_status="unverified")
        no_provenance = replace(good, finding_reference=reference("no-provenance"), provenance=None)
        result = self.adapter.evaluate(replace(complete_request(), findings=(good, unverified, no_provenance)))
        self.assertEqual(result.status, "needs_data")
        self.assertEqual(result.eligible_finding_references, (good.finding_reference,))
        checks = {check.finding_reference: check for check in result.finding_checks}
        self.assertTrue(checks[good.finding_reference].eligible)
        self.assertEqual(checks[good.finding_reference].verification_codes, ())
        self.assertEqual(checks[good.finding_reference].provenance_codes, ())
        self.assertFalse(checks[unverified.finding_reference].eligible)
        self.assertEqual(checks[unverified.finding_reference].verification_codes, ("finding_not_verified",))
        self.assertEqual(checks[no_provenance.finding_reference].provenance_codes, ("missing_finding_provenance",))

    def test_verified_flag_is_insufficient_without_complete_provenance(self):
        for provenance in (None, FindingProvenance()):
            with self.subTest(provenance=provenance):
                finding = replace(reviewed_finding(), provenance=provenance)
                result = self.adapter.evaluate(replace(complete_request(), findings=(finding,)))
                self.assertEqual(result.status, "needs_data")
                self.assertEqual(result.eligible_finding_references, ())
                self.assertTrue(self.codes(result, "finding_provenance"))

    def test_provenance_is_pinned_to_instance_digest_schema_and_review_policy(self):
        for changes, expected_code in (
            ({"source_instance_reference": reference("another-instance")}, "finding_source_metadata_mismatch"),
            ({"source_metadata_sha256": "b" * 64}, "finding_source_metadata_mismatch"),
            ({"source_metadata_schema_version": "imaging-metadata-v2"}, "finding_source_metadata_mismatch"),
            ({"review_policy_version": "finding-review-v2"}, "unsupported_finding_review_policy"),
            ({"review_record_reference": None}, "incomplete_finding_provenance"),
        ):
            with self.subTest(changes=changes):
                finding = reviewed_finding()
                finding = replace(finding, provenance=replace(finding.provenance, **changes))
                result = self.adapter.evaluate(replace(complete_request(), findings=(finding,)))
                self.assertEqual(result.eligible_finding_references, ())
                self.assertIn(expected_code, self.codes(result, "finding_provenance"))

    def test_findings_without_available_source_metadata_are_blocked(self):
        adapter = RuleBasedDecisionAdapter(EvaluationRequirements(require_imaging=False))
        result = adapter.evaluate(replace(complete_request(), imaging=None))
        self.assertEqual(result.status, "needs_data")
        self.assertEqual(result.eligible_finding_references, ())
        self.assertIn("finding_source_metadata_unavailable", self.codes(result, "finding_provenance"))

    def test_required_verified_finding_count_counts_eligible_findings_only(self):
        adapter = RuleBasedDecisionAdapter(EvaluationRequirements(minimum_verified_findings=1))
        request = replace(complete_request(), findings=())
        result = adapter.evaluate(request)
        self.assertEqual(result.status, "needs_data")
        self.assertIn("insufficient_verified_findings", self.codes(result, "finding_completeness"))
        self.assertEqual(adapter.evaluate(complete_request()).status, "data_ready")

    def test_schema_errors_fail_closed_with_no_echoed_values(self):
        secret = "Jane Doe 2000-01-01 patient record"
        cases = (
            {"clinical": secret},
            replace(complete_request(), clinical=secret),
            replace(complete_request(), clinical=ClinicalInput(available_fields=["clinical_review"])),
            replace(complete_request(), imaging=replace(complete_imaging(), modality=secret)),
            replace(complete_request(), imaging=replace(complete_imaging(), study_reference="1.2.840.999")),
            replace(complete_request(), imaging=replace(complete_imaging(), metadata_sha256="not-a-digest")),
            replace(complete_request(), findings=[reviewed_finding()]),
            replace(complete_request(), findings=(replace(reviewed_finding(), finding_code=secret),)),
            replace(complete_request(), findings=(replace(reviewed_finding(), provenance=secret),)),
        )
        for request in cases:
            with self.subTest(request_type=type(request).__name__):
                result = self.adapter.evaluate(request)
                self.assertEqual(result.status, "invalid_input")
                self.assertIsNone(result.input_sha256)
                self.assertEqual(result.eligible_finding_references, ())
                self.assertEqual(result.blocked_finding_references, ())
                self.assertEqual(result.next_steps, ("correct_input_schema",))
                serialized = json.dumps(result.to_dict())
                self.assertNotIn(secret, serialized)
                self.assertNotIn("1.2.840.999", serialized)
                self.assertTrue(all(t.outcome == "not_applicable" for t in result.traces[1:]))

    def test_duplicate_finding_references_fail_closed(self):
        finding = reviewed_finding()
        result = self.adapter.evaluate(replace(complete_request(), findings=(finding, finding)))
        self.assertEqual(result.status, "invalid_input")
        self.assertIn("duplicate_finding_reference", self.codes(result, "input_schema"))
        self.assertEqual(result.eligible_finding_references, ())

    def test_imaging_identity_references_must_be_distinct(self):
        imaging = complete_imaging()
        for identity_field in ("series_reference", "instance_reference"):
            with self.subTest(identity_field=identity_field):
                imaging = replace(imaging, **{identity_field: imaging.study_reference})
                result = self.adapter.evaluate(replace(complete_request(), imaging=imaging))
                self.assertEqual(result.status, "invalid_input")
                self.assertIn("duplicate_imaging_identity_reference", self.codes(result, "input_schema"))
                self.assertEqual(result.eligible_finding_references, ())

    def test_unknown_reader_schema_blocks_readiness(self):
        imaging = replace(complete_imaging(), metadata_schema_version="imaging-metadata-v2")
        result = self.adapter.evaluate(replace(complete_request(), imaging=imaging))
        self.assertEqual(result.status, "needs_data")
        self.assertIn("unsupported_metadata_schema_version", self.codes(result, "imaging_completeness"))

    def test_digest_determinism_and_semantic_changes(self):
        request = complete_request()
        first = self.adapter.evaluate(request)
        second = RuleBasedDecisionAdapter().evaluate(request)
        self.assertEqual(first, second)
        changed = self.adapter.evaluate(replace(request, findings=()))
        self.assertNotEqual(first.input_sha256, changed.input_sha256)
        self.assertEqual(first.rules_sha256, changed.rules_sha256)
        self.assertNotEqual(first.result_sha256, changed.result_sha256)
        other_policy = RuleBasedDecisionAdapter(EvaluationRequirements(policy_version="data-requirements-v2"))
        policy_result = other_policy.evaluate(request)
        self.assertEqual(first.input_sha256, policy_result.input_sha256)
        self.assertNotEqual(first.rules_sha256, policy_result.rules_sha256)
        self.assertNotEqual(first.result_sha256, policy_result.result_sha256)
        payload = first.to_dict()
        payload.pop("result_sha256")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(hashlib.sha256(canonical.encode("ascii")).hexdigest(), first.result_sha256)

    def test_requirements_changes_alter_rule_digest_even_if_version_is_unchanged(self):
        other = RuleBasedDecisionAdapter(EvaluationRequirements(required_technical_fields=("rows",)))
        self.assertNotEqual(self.adapter.rules_sha256, other.rules_sha256)

    def test_no_clinical_codes_or_metadata_are_echoed_into_a_result(self):
        finding = replace(reviewed_finding(), finding_code="sensitive_coded_observation")
        result = self.adapter.evaluate(replace(complete_request(), findings=(finding,)))
        serialized = json.dumps(result.to_dict())
        self.assertNotIn("sensitive_coded_observation", serialized)
        self.assertNotIn("KNEE", serialized)
        self.assertNotIn("patient", serialized)
        self.assertNotIn("diagnosis", result.to_dict())
        self.assertNotIn("treatment", result.to_dict())

    def test_inputs_results_and_effective_policy_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            complete_request().clinical = ClinicalInput()
        with self.assertRaises(FrozenInstanceError):
            self.adapter.requirements = EvaluationRequirements(policy_version="changed")
        with self.assertRaises(FrozenInstanceError):
            self.adapter.evaluate(complete_request()).status = "data_ready"

    def test_malformed_requirement_configuration_is_rejected(self):
        for requirements in (
            EvaluationRequirements(required_clinical_fields=("unrecognized_field",)),
            EvaluationRequirements(required_clinical_fields=["clinical_review"]),
            EvaluationRequirements(minimum_verified_findings=True),
            EvaluationRequirements(minimum_verified_findings=-1),
            EvaluationRequirements(required_technical_fields=("patient_name",)),
            EvaluationRequirements(required_technical_fields=("pixel_data_present",)),
            EvaluationRequirements(expected_modality="invented"),
            EvaluationRequirements(policy_version="Patient Name"),
        ):
            with self.subTest(requirements=requirements):
                with self.assertRaisesRegex(ValueError, "Invalid evaluation requirements"):
                    RuleBasedDecisionAdapter(requirements)


if __name__ == "__main__":
    unittest.main()
