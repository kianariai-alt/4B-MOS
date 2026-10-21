"""Opt-in tests on actual pinned producer code in a disposable composition.

Run explicitly after compose_clinical_handoff, never skip missing producer code.
No patient data, external services, model weights or specialist approval exist.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from backend.app.schemas import clinical_integration as contract
from backend.app.schemas.clinical_integration import IntegrationIssue, KnowledgeReference, VisitReference
from backend.app.services.clinical_integration.adapters import local_adapters, source_bundle
from backend.app.services.clinical_integration.engine import assemble_result, collect_cores
from backend.app.services.physician_copilot import PhysicianCopilotService
from backend.app.decision_intelligence import ClinicalInput
from backend.app.imaging_intelligence.integration import GatedImagingRecordAdapter, ReportSeriesBinding
from backend.app.imaging_intelligence.series import SeriesMetadataReader, StudySeriesValidator
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext
from backend.app.services.orthopedic_adapter import build_decision_knowledge
from backend.tools.clinical_handoff_report import (
    HandoffVerificationError, build_report, load_json, validate_authoring_preview,
)
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.imaging_series_demo import generate_synthetic_series

ROOT = Path(__file__).resolve().parents[2]


def _producer_context():
    return OrthopedicQuestionContext.model_validate({"body_region": "knee", "observations": [
        {"field": "onset", "state": "confirmed", "value": "gradual",
         "provenance": "patient_report", "source_ref": "synthetic:intake-v1"},
        {"field": "pain_score", "state": "confirmed", "value": 6,
         "provenance": "patient_report", "source_ref": "synthetic:intake-v1"},
        {"field": "imaging_kl_grade", "state": "unverified", "value": 2,
         "provenance": "unreviewed_imaging", "source_ref": "synthetic:report-v1"},
    ]})


def test_actual_authoring_producer_reproduces_pinned_fixture_and_cannot_be_promoted():
    payload = load_json(ROOT / "docs/examples/orthopedic-knee-synthetic-preview.json")
    produced = build_decision_knowledge(_producer_context())
    assert produced.model_dump(mode="json") == payload
    assert produced.approved_fact_count == 0
    assert produced.unverified_findings[0].state == "unverified"
    assert all(item.provenance == "patient_report" for item in produced.structured_symptoms)
    with pytest.raises(ValidationError):
        contract.CoreOutput.model_validate(payload)
    for draft in payload["evidence_references"]:
        with pytest.raises(ValidationError):
            KnowledgeReference.model_validate(draft)


@pytest.mark.parametrize("field,value", [
    ("approved_fact_count", 1), ("governance_status", "approved"),
    ("authorizes_treatment", True), ("is_clinical_clearance", True),
    ("safety_evaluation", "no_alerts"), ("result_sha256", "0" * 64),
])
def test_schema_and_consumer_reject_changed_authority_or_integrity_claims(field, value):
    payload = load_json(ROOT / "docs/examples/orthopedic-knee-synthetic-preview.json")
    schema = load_json(ROOT / "docs/contracts/orthopedic-decision-knowledge-1.0.0.schema.json")
    payload[field] = value
    with pytest.raises(HandoffVerificationError):
        validate_authoring_preview(payload, schema)


def test_receipt_is_repeatable_contains_no_medical_text_and_records_both_boundaries():
    first = build_report(ROOT)
    assert first == build_report(ROOT)
    assert first["imaging"]["core_contract"] == "accepted"
    assert first["imaging"]["clinical_clearance"] is False
    assert first["orthopedic"]["disposition"] == "draft_quarantined"
    assert first["orthopedic"]["clinical_context_binding"] == "not_established"
    assert first["orthopedic"]["approved_fact_count"] == 0
    assert first["is_clinical_validation"] is first["specialist_code_activated_in_api"] is False
    text = json.dumps(first)
    assert all(item not in text for item in ["patient_id", "visit_id", "source_ref", "https://", "statement"])


@pytest.fixture
def actual_image_adapter(tmp_path):
    fixture = generate_synthetic_series(tmp_path)
    study = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)).read(
        fixture.files, expected=(fixture.expected,),
    )
    source = contract.RecordReference(
        record_type="paraclinical_report", record_id="synthetic-report", version=1,
        content_sha256="b" * 64, observation_id="synthetic-observation", field="observation",
    )
    context = contract.CoreInput(visit_id="synthetic-visit", clinical_context_sha256="c" * 64,
        observations=(contract.SourceObservation(source=source, observation={
            "category": "imaging", "code_system": "LOCAL", "code": "SYNTHETIC_ONLY",
            "display_name": "Fabricated record", "value_type": "boolean", "boolean_value": True,
        }),))
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    adapter = GatedImagingRecordAdapter(
        study=study, binding=ReportSeriesBinding(source.record_id, 1, source.content_sha256,
                                                context.clinical_context_sha256, study.series[0].sha256),
        clinical=ClinicalInput(("assessment_context", "clinical_review"), "KNEE", "L"),
        contract=contract, clock=lambda: now,
    )
    return adapter, context, now


def test_actual_series_adapter_works_with_strict_current_contract_without_review_authority(actual_image_adapter):
    adapter, context, now = actual_image_adapter
    assert adapter.validation().status == "data_ready"
    cores, issues = collect_cores(context, {**local_adapters(), "imaging": adapter}, now=now)
    assert cores[1].status == "available"
    assert cores[1].findings[0].observation == context.observations[0].observation
    result = assemble_result(
        patient_id="synthetic-patient", visit=VisitReference(visit_id=context.visit_id, status="open"),
        context=context, assessment=None, studies=(), approvals={}, cores=cores, knowledge=(),
        copilot_sha256="d" * 64, safety_rule_set_sha256="e" * 64,
        issues=issues + (IntegrationIssue(code="safety_evaluation_missing", severity="blocking"),), now=now,
    )
    assert result.confirmed_findings == ()
    assert result.unreviewed_findings[0].review_status == "unreviewed_source"
    assert result.workflow_state == "blocked"
    assert result.is_clinical_clearance is result.authorizes_treatment is False


@pytest.mark.parametrize("changed", ["report_version", "series", "context", "clinical", "study"])
def test_actual_producer_rejects_changed_handoff_dependencies(actual_image_adapter, changed):
    adapter, context, now = actual_image_adapter
    args = dict(study=adapter.study, binding=adapter.binding, clinical=adapter.clinical,
                contract=contract, clock=lambda: now)
    if changed == "report_version":
        args["binding"] = replace(adapter.binding, report_version=2)
    elif changed == "series":
        args["binding"] = replace(adapter.binding, series_sha256="f" * 64)
    elif changed == "context":
        args["binding"] = replace(adapter.binding, clinical_context_sha256="f" * 64)
    elif changed == "clinical":
        args["clinical"] = ClinicalInput()
    else:
        args["study"] = replace(adapter.study, status="invalid")
    changed_adapter = GatedImagingRecordAdapter(**args)
    assert changed_adapter.current_version() != adapter.current_version()
    output = changed_adapter.collect(context)
    assert output.status == "unavailable" and output.findings == ()


def test_actual_producer_cannot_omit_unbound_imaging_source(actual_image_adapter):
    adapter, context, now = actual_image_adapter
    original = context.observations[0]
    extra = original.model_copy(update={"source": original.source.model_copy(update={"record_id": "other-report"})})
    context = context.model_copy(update={"observations": context.observations + (extra,)})
    cores, issues = collect_cores(context, {**local_adapters(), "imaging": adapter}, now=now)
    assert cores[1].status == "unavailable"
    assert cores[1].findings == ()


# Use the existing isolated in-memory SQLite fixtures, not a new database setup.
from backend.tests.conftest import reset_database, authenticated_admin, client, db_session, admin_headers
from backend.tests.test_clinical_integration import visit, physician, inputs, enable_preview
from backend.app.api.routes.clinical_integration import get_integration_adapters
from backend.app.main import app


@pytest.mark.usefixtures("authenticated_admin")
def test_readonly_api_preserves_source_authority_and_changes_hash_with_series(
    client, db_session, visit, inputs, tmp_path,
):
    fixture = generate_synthetic_series(tmp_path)
    study = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)).read(
        fixture.files, expected=(fixture.expected,),
    )
    copilot = PhysicianCopilotService.get_snapshot(db_session, visit["id"])
    bundle = source_bundle(db_session, copilot.clinical_context, copilot.manifest.clinical_context_sha256)
    source = next(item.source for item in bundle.core_input.observations if item.observation.category == "imaging")
    args = dict(study=study, binding=ReportSeriesBinding(
        source.record_id, source.version, source.content_sha256,
        bundle.core_input.clinical_context_sha256, study.series[0].sha256,
    ), clinical=ClinicalInput(("assessment_context", "clinical_review"), "KNEE", "L"), contract=contract)
    adapters = {**local_adapters(), "imaging": GatedImagingRecordAdapter(**args)}
    app.dependency_overrides[get_integration_adapters] = lambda: adapters
    url = f"/api/v1/visits/{visit['id']}/clinical-intelligence"
    response = client.get(url)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["snapshot_sha256"] == client.get(url).json()["snapshot_sha256"]
    assert first["result"]["imaging_studies"][0]["dicom_identity_verified"] is False
    assert any(item["core"] == "imaging" for item in first["result"]["confirmed_findings"])
    assert first["is_clinical_clearance"] is first["authorizes_treatment"] is False
    args["study"] = replace(study, status="invalid")
    adapters["imaging"] = GatedImagingRecordAdapter(**args)
    changed = client.get(url)
    assert changed.status_code == 200, changed.text
    second = changed.json()
    assert second["snapshot_sha256"] != first["snapshot_sha256"]
    assert second["status"] == "degraded"
    assert not any(item["core"] == "imaging" for item in second["result"]["confirmed_findings"])
