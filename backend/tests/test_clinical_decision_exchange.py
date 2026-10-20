"""Synthetic-only decision exchange; no inference service or patient database."""

from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
import pytest

from backend.app.schemas.clinical_decision_exchange import (
    DecisionModelReference, DecisionModelResult, DecisionSignal, decision_digest,
)
from backend.app.schemas.clinical_integration import CoreInput, CoreOutput, KnowledgeReference
from backend.app.services.clinical_integration.decision import (
    MockDecisionAdapter, MockImagingAdapter, MockOrthopedicAdapter, collect_decision,
    synthetic_core_input,
)

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def test_three_synthetic_adapters_share_existing_contracts_and_remain_unverified():
    context = synthetic_core_input()
    for adapter, name in [(MockOrthopedicAdapter(now=NOW), "orthopedic"),
                          (MockImagingAdapter(now=NOW), "imaging")]:
        output = adapter.collect(context)
        assert CoreOutput.model_validate_json(output.model_dump_json()) == output
        assert output.core == name
        assert len(output.findings) == 1
        assert output.findings[0].origin == "record"
    reference = collect_decision(context, MockDecisionAdapter(now=NOW), now=NOW)
    assert reference.status == "available"
    assert reference.result.review_status == "unverified"
    assert reference.result_sha256 == decision_digest(reference.result)
    assert reference.usable_as_confirmed_finding is False
    assert reference.is_clinical_clearance is reference.authorizes_treatment is False
    assert reference.result.is_diagnosis is reference.result.is_recommendation is False
    assert DecisionModelReference.model_validate_json(reference.model_dump_json()) == reference


@pytest.mark.parametrize("adapter_type", [MockOrthopedicAdapter, MockImagingAdapter, MockDecisionAdapter])
@pytest.mark.parametrize("change", ["visit", "context_hash", "value", "source_hash"])
def test_mocks_reject_arbitrary_patient_data_even_with_synthetic_looking_ids(adapter_type, change):
    data = synthetic_core_input().model_dump(mode="json")
    if change == "visit":
        data["visit_id"] = "synthetic-but-not-the-fixed-case"
    elif change == "context_hash":
        data["clinical_context_sha256"] = "d" * 64
    elif change == "value":
        data["observations"][0]["observation"]["boolean_value"] = False
    else:
        data["observations"][0]["source"]["content_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="fixed synthetic fixture"):
        adapter_type(now=NOW).collect(CoreInput.model_validate(data))


@pytest.mark.parametrize("field,value", [
    ("review_status", "verified"), ("usable_as_confirmed_finding", True),
    ("is_diagnosis", True), ("is_recommendation", True), ("is_clinical_clearance", True),
    ("authorizes_treatment", True), ("physician_user_id", "invented-reviewer"),
    ("schema_version", "2.0.0"), ("treatment_rankings", ["fake-choice"]),
])
def test_producer_cannot_claim_review_or_final_clinical_authority(field, value):
    output = MockDecisionAdapter(now=NOW).collect(synthetic_core_input()).model_dump(mode="json")
    output[field] = value
    with pytest.raises(ValidationError):
        DecisionModelResult.model_validate(output)


@pytest.mark.parametrize("change", ["nan", "infinity", "empty_limitations", "naive", "expiry",
                                    "duplicate_source", "duplicate_signal", "not_model", "unknown_signal"])
def test_malformed_decision_contract_rejected(change):
    output = MockDecisionAdapter(now=NOW).collect(synthetic_core_input()).model_dump(mode="json")
    if change == "nan":
        output["signals"][0]["value"] = float("nan")
    elif change == "infinity":
        output["signals"][0]["value"] = float("inf")
    elif change == "empty_limitations":
        output["limitations"] = []
    elif change == "naive":
        output["generated_at"] = NOW.replace(tzinfo=None).isoformat()
    elif change == "expiry":
        output["valid_until"] = output["generated_at"]
    elif change == "duplicate_source":
        output["source_references"].append(output["source_references"][0])
    elif change == "duplicate_signal":
        output["signals"].append(output["signals"][0])
    elif change == "not_model":
        output["component"]["kind"] = "adapter"
    else:
        output["signals"][0]["code"] = "diagnosis"
    with pytest.raises(ValidationError):
        DecisionModelResult.model_validate(output)


@pytest.mark.parametrize("change", ["visit", "context", "source_version", "model_version", "artifact", "future"])
def test_invocation_and_provenance_mismatch_is_excluded(change):
    context = synthetic_core_input()

    class Changed(MockDecisionAdapter):
        def collect(self, context):
            data = super().collect(context).model_dump(mode="json")
            if change == "visit":
                data["visit_id"] = "different-visit"
            elif change == "context":
                data["clinical_context_sha256"] = "e" * 64
            elif change == "source_version":
                data["source_references"][0]["version"] = 2
            elif change == "model_version":
                data["component"]["version"] = "untrusted-new-version"
            elif change == "artifact":
                data["component"]["artifact_sha256"] = "e" * 64
            else:
                data["generated_at"] = (NOW + timedelta(minutes=6)).isoformat()
            return DecisionModelResult.model_validate(data)

    reference = collect_decision(context, Changed(now=NOW), now=NOW)
    assert reference.status == "invalid"
    assert reference.result is reference.result_sha256 is None
    assert reference.issue_codes == ("decision_output_invalid",)


def test_absent_expired_and_failed_models_are_explicit_and_secret_safe():
    context = synthetic_core_input()
    assert collect_decision(context, None, now=NOW).status == "missing"
    expired = collect_decision(context, MockDecisionAdapter(now=NOW - timedelta(hours=2)), now=NOW)
    assert expired.status == "expired"
    assert expired.result is None

    class Failed(MockDecisionAdapter):
        def collect(self, context):
            raise RuntimeError("secret-patient-text https://example.test/image?token=secret-value")

    failed = collect_decision(context, Failed(now=NOW), now=NOW)
    assert failed.status == "unavailable"
    assert "secret" not in failed.model_dump_json()
    assert "example.test" not in failed.model_dump_json()
    assert failed.result is None


def test_decision_hash_is_stable_for_equivalent_serialization_and_changes_with_model_version():
    output = MockDecisionAdapter(now=NOW).collect(synthetic_core_input())
    parsed = DecisionModelResult.model_validate_json(output.model_dump_json())
    assert decision_digest(parsed) == decision_digest(output)
    changed = output.model_copy(update={"component": output.component.model_copy(update={"version": "2.0.0"})})
    assert decision_digest(changed) != decision_digest(output)


def test_reference_cannot_publish_mismatched_digest_or_excluded_output():
    reference = collect_decision(synthetic_core_input(), MockDecisionAdapter(now=NOW), now=NOW)
    data = reference.model_dump(mode="json")
    data["result_sha256"] = "e" * 64
    with pytest.raises(ValidationError):
        DecisionModelReference.model_validate(data)
    data = reference.model_dump(mode="json")
    data["status"] = "expired"
    with pytest.raises(ValidationError):
        DecisionModelReference.model_validate(data)


def test_nested_signal_fields_do_not_silently_disappear():
    with pytest.raises(ValidationError):
        DecisionSignal(code="research_score", value=0.5, diagnosis="unsupported")


def test_model_cannot_introduce_unapproved_or_expired_knowledge():
    reference = KnowledgeReference(
        fact_id="synthetic-fact", fact_key="synthetic-key", version=1,
        content_sha256="f" * 64, evidence_grade="synthetic-not-clinical",
        source_ids=("synthetic-source",), valid_to=NOW.date(),
    )

    class WithKnowledge(MockDecisionAdapter):
        def collect(self, context):
            return super().collect(context).model_copy(update={"knowledge": (reference,)})

    context = synthetic_core_input()
    adapter = WithKnowledge(now=NOW)
    assert collect_decision(context, adapter, now=NOW).status == "invalid"
    bound = collect_decision(context, adapter, now=NOW, approved_knowledge=(reference,))
    assert bound.status == "available"
    assert bound.result.knowledge[0].applicability == "not_assessed"
    assert collect_decision(context, adapter, now=NOW + timedelta(days=1),
                            approved_knowledge=(reference,)).status == "invalid"
    changed = reference.model_copy(update={"version": 2})
    assert collect_decision(context, adapter, now=NOW, approved_knowledge=(changed,)).status == "invalid"


def test_model_cannot_extend_its_own_freshness_window_indefinitely():
    class OldOutput(MockDecisionAdapter):
        def collect(self, context):
            output = super().collect(context)
            return output.model_copy(update={"valid_until": NOW + timedelta(days=365)})

    reference = collect_decision(synthetic_core_input(),
                                 OldOutput(now=NOW - timedelta(days=2)), now=NOW)
    assert reference.status == "expired"
    assert reference.result is None
