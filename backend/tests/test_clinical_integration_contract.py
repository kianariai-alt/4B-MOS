"""Synthetic producer compatibility and explicit safety invariants."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from backend.app.schemas.clinical_integration import (
    CoreInput, CoreOutput, DecisionSupportResult, IntegratedFinding, IntegrationRunCreate,
    SourceObservation,
)
from backend.app.services.clinical_integration.adapters import FinalRecordAdapter, local_adapters
from backend.app.services.clinical_integration.engine import assemble_result, collect_cores, digest_model
from backend.tools.clinical_integration_demo import synthetic_result


def test_synthetic_two_core_round_trip_and_traceability():
    result = synthetic_result()
    assert DecisionSupportResult.model_validate_json(result.model_dump_json()) == result
    assert [core.core for core in result.cores] == ["orthopedic", "imaging"]
    assert len(result.confirmed_findings) == 2
    assert all(item.approval for item in result.confirmed_findings)
    assert result.unreviewed_findings == ()
    assert result.is_diagnosis is result.is_recommendation is result.authorizes_treatment is False
    assert len(result.provenance.core_output_sha256s) == 2


@pytest.mark.parametrize("field,value", [
    ("contract_version", "2.0.0"), ("patient_name", "Must not be accepted"),
    ("review_status", "approved"), ("is_approved", True),
])
def test_producer_cannot_add_approval_demographics_or_incompatible_version(field, value):
    core = synthetic_result().cores[1].model_dump(mode="json")
    core[field] = value
    with pytest.raises(ValidationError):
        CoreOutput.model_validate(core)


@pytest.mark.parametrize("change", ["duplicate", "nan", "naive_timestamp", "nonmodel_probability", "unavailable_findings"])
def test_invalid_producer_shapes_fail_closed(change):
    core = synthetic_result().cores[1].model_dump(mode="json")
    if change == "duplicate":
        core["findings"].append(deepcopy(core["findings"][0]))
    elif change == "nan":
        core["findings"][0].update(origin="model", confidence=float("nan"))
        core["component"]["kind"] = "model"
    elif change == "naive_timestamp":
        core["generated_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    elif change == "nonmodel_probability":
        core["findings"][0]["confidence"] = 1
    else:
        core["status"] = "unavailable"
    with pytest.raises(ValidationError):
        CoreOutput.model_validate(core)


def test_request_rejects_client_review_claims_and_duplicate_knowledge():
    with pytest.raises(ValidationError):
        IntegrationRunCreate(request_key="a", expected_clinical_context_sha256="a" * 64,
                             knowledge_fact_ids=("same", "same"))
    with pytest.raises(ValidationError):
        IntegrationRunCreate(request_key="a", expected_clinical_context_sha256="a" * 64,
                             imaging_approved=True)


@pytest.mark.parametrize("field,value", [
    ("quality_limitations", ["Synthetic motion artifact"]),
    ("review_status", "approved"),
    ("is_clinical_clearance", True),
])
def test_nested_observation_cannot_silently_drop_unsupported_producer_fields(field, value):
    core = synthetic_result().cores[1].model_dump(mode="json")
    core["findings"][0]["observation"][field] = value
    with pytest.raises(ValidationError):
        CoreOutput.model_validate(core)
    source = {"source": core["findings"][0]["source"],
              "observation": core["findings"][0]["observation"]}
    with pytest.raises(ValidationError):
        SourceObservation.model_validate(source)


@pytest.mark.parametrize("change", [
    "model_confirmed", "missing_approval", "unreviewed_approval", "unreviewed_usable", "wrong_origin_status",
])
def test_integrated_findings_enforce_source_finalization_and_model_review_boundary(change):
    finding = synthetic_result().confirmed_findings[1].model_dump(mode="json")
    if change == "model_confirmed":
        finding["finding"].update(origin="model", confidence=0.999)
    elif change == "missing_approval":
        finding["approval"] = None
    elif change == "unreviewed_approval":
        finding.update(review_status="unreviewed_source", usable_as_confirmed_finding=False)
    elif change == "unreviewed_usable":
        finding.update(review_status="unreviewed_source", approval=None)
    else:
        finding.update(review_status="unreviewed_model", approval=None, usable_as_confirmed_finding=False)
    with pytest.raises(ValidationError):
        IntegratedFinding.model_validate(finding)


@pytest.mark.parametrize("change", ["model_in_confirmed", "confirmed_in_unreviewed", "duplicate", "blocking_ready"])
def test_result_cannot_mislabel_review_collections_or_approval_readiness(change):
    result = synthetic_result().model_dump(mode="json")
    if change == "model_in_confirmed":
        finding = result["confirmed_findings"][1]
        finding["finding"].update(origin="model", confidence=0.999)
        finding.update(review_status="unreviewed_model", approval=None, usable_as_confirmed_finding=False)
        result["workflow_state"] = "blocked"
    elif change == "confirmed_in_unreviewed":
        result["unreviewed_findings"].append(result["confirmed_findings"].pop())
        result["workflow_state"] = "blocked"
    elif change == "duplicate":
        result["confirmed_findings"].append(deepcopy(result["confirmed_findings"][0]))
    else:
        result["issues"].append({"code": "synthetic_safety_alert", "severity": "blocking"})
    with pytest.raises(ValidationError):
        DecisionSupportResult.model_validate(result)


@pytest.mark.parametrize("remaining", [0, 1])
def test_partial_and_empty_producer_output_preserves_omitted_sources_and_blocks_summary(remaining):
    initial = synthetic_result()
    original = tuple(SourceObservation(source=item.source, observation=item.observation)
                     for core in initial.cores for item in core.findings)
    second_image = original[1].model_copy(update={"source": original[1].source.model_copy(update={
        "record_id": "synthetic-second-report", "observation_id": "synthetic-second-observation",
    })})
    context = CoreInput(visit_id=initial.visit.visit_id,
                        clinical_context_sha256=initial.provenance.clinical_context_sha256,
                        observations=original + (second_image,))

    class OmittingImagingAdapter(FinalRecordAdapter):
        def collect(self, producer_input):
            output = super().collect(producer_input)
            return output.model_copy(update={"findings": output.findings[:remaining]})

    cores, issues = collect_cores(context, local_adapters() | {
        "imaging": OmittingImagingAdapter("imaging"),
    }, now=initial.generated_at)
    result = assemble_result(
        patient_id=initial.patient.patient_id, visit=initial.visit, context=context,
        assessment=initial.assessment, studies=initial.imaging_studies,
        approvals={digest_model(item.source): initial.confirmed_findings[0].approval
                   for item in context.observations},
        cores=cores, knowledge=(), copilot_sha256=initial.provenance.copilot_snapshot_sha256,
        safety_rule_set_sha256=initial.provenance.safety_rule_set_sha256,
        issues=issues, now=initial.generated_at,
    )
    omitted = next(issue for issue in result.issues if issue.code == "incomplete_core_coverage")
    assert omitted.core == "imaging" and omitted.severity == "blocking"
    assert omitted.source_references == tuple(item.source for item in context.observations[1 + remaining:])
    assert all(source in result.raw_record_references for source in omitted.source_references)
    assert len(result.confirmed_findings) == 1 + remaining
    assert result.workflow_state == "blocked"


def test_published_producer_schema_matches_the_current_contract():
    schema = Path(__file__).resolve().parents[2] / "docs/contracts/unified-clinical-core-output-1.0.0.schema.json"
    assert json.loads(schema.read_text(encoding="utf-8")) == CoreOutput.model_json_schema()
