"""Read-only snapshots over synthetic in-memory SQLite records only."""

import json

import pytest
from sqlalchemy import event, select, update

from backend.app.api.routes.clinical_integration import get_integration_adapters, get_decision_adapter
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.clinical_integration import ClinicalIntegrationRun, ClinicalIntegrationReview
from backend.app.models.clinical_context import ParaclinicalReport
from backend.app.schemas.clinical_intelligence import IntegratedClinicalSnapshot
from backend.app.services.clinical_integration.adapters import FinalRecordAdapter, local_adapters
from backend.app.services.clinical_integration.read_only import snapshot_digest
from backend.tests.test_clinical_integration import (
    visit, physician, inputs, enable_preview, add_report, evaluate, MutableAdapter,
)
from backend.tests.test_physician_copilot import create_role_headers

pytestmark = pytest.mark.usefixtures("authenticated_admin")


def url(visit):
    return f"/api/v1/visits/{visit['id']}/clinical-intelligence"


def test_read_only_snapshot_stable_hash_and_no_writes(client, visit, inputs, db_session):
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first = client.get(url(visit))
        second = client.get(url(visit))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert first.status_code == second.status_code == 200, first.text
    result, repeated = first.json(), second.json()
    assert first.headers["Cache-Control"] == "no-store"
    assert result["snapshot_sha256"] == repeated["snapshot_sha256"]
    assert result["provenance_manifest"] == repeated["provenance_manifest"]
    assert snapshot_digest(IntegratedClinicalSnapshot.model_validate(result)) == result["snapshot_sha256"]
    assert result["safety_status"]["status"] == "no_active_rules"
    assert result["safety_status"]["evaluation"]["evaluation_id"]
    assert result["imaging_review"][0]["review_status"] == "verified"
    assert result["decision_model_reference"]["status"] == "missing"
    assert result["review_status"] == "requires_physician_review"
    assert result["is_diagnosis"] is result["is_clinical_clearance"] is False
    assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
    assert db_session.scalar(select(ClinicalIntegrationRun)) is None
    assert db_session.scalar(select(ClinicalIntegrationReview)) is None
    manifest = json.dumps(result["provenance_manifest"])
    assert all(text not in manifest for text in ["patient_id", "visit_id", "Synthetic", "token=", "https://"])


def test_empty_visit_valid_imaging_unavailable_snapshot(client, visit):
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "imaging_unavailable"
    assert data["safety_status"]["status"] == "missing"
    assert data["result"]["confirmed_findings"] == []
    assert "final_clinical_assessment_missing" in data["review_requirements"]


def test_imaging_lifecycle_excludes_draft_rejected_and_invalid_sources(client, visit, inputs, physician):
    old = inputs["report"]
    assert client.post(f"/api/v1/paraclinical-reports/{old['id']}/entered-in-error",
                       json={"reason": "Synthetic source withdrawn for independent review."},
                       headers=physician).status_code == 200
    draft = add_report(client, visit, physician, key="DRAFT-MRI", finalize=False)
    evaluate(client, visit)
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    reviews = {item["report_id"]: item for item in data["imaging_review"]}
    assert reviews[old["id"]]["review_status"] == "rejected"
    assert reviews[draft["id"]]["review_status"] == "unverified"
    assert data["status"] == "imaging_unavailable"
    assert all(item["core"] != "imaging" for item in data["result"]["confirmed_findings"])


def test_admin_finalization_stays_unverified(client, visit, inputs, physician):
    report = add_report(client, visit, physician, key="ADMIN-REPORT", finalize=False)
    assert client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize").status_code == 200
    evaluate(client, visit)
    data = client.get(url(visit)).json()
    assert next(item for item in data["imaging_review"] if item["report_id"] == report["id"])["review_status"] == "unverified"
    assert data["result"]["unreviewed_findings"]
    assert data["status"] == "degraded"


@pytest.mark.parametrize("mode", ["timeout", "wrong_visit", "expired", "forged", "model"])
def test_adapter_failures_and_ai_results_never_become_confirmed(client, visit, inputs, mode):
    adapter = MutableAdapter("imaging")
    adapter.mode = mode
    app.dependency_overrides[get_integration_adapters] = lambda: {**local_adapters(), "imaging": adapter}
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "degraded"
    assert data["result"]["workflow_state"] == "blocked"
    assert all(item["core"] != "imaging" for item in data["result"]["confirmed_findings"])
    assert "secret-link" not in response.text and "NEVER-LEAK" not in response.text


def test_omitted_source_blocks_summary_and_lists_source_reference(client, visit, inputs):
    class OmittingAdapter(FinalRecordAdapter):
        def collect(self, context):
            return super().collect(context).model_copy(update={"findings": ()})
    app.dependency_overrides[get_integration_adapters] = lambda: {
        **local_adapters(), "imaging": OmittingAdapter("imaging"),
    }
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    issue = next(item for item in response.json()["result"]["issues"] if item["code"] == "incomplete_core_coverage")
    assert issue["severity"] == "blocking"
    assert issue["source_references"][0]["record_id"] == inputs["report"]["id"]


def test_ancient_core_cannot_extend_its_own_validity(client, visit, inputs):
    from datetime import timedelta
    class AncientAdapter(FinalRecordAdapter):
        def collect(self, context):
            output = super().collect(context)
            return output.model_copy(update={"generated_at": output.generated_at - timedelta(days=90)})
    app.dependency_overrides[get_integration_adapters] = lambda: {
        **local_adapters(), "imaging": AncientAdapter("imaging"),
    }
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    assert "expired_core_output" in data["review_requirements"]
    assert not any(item["core"] == "imaging" for item in data["result"]["confirmed_findings"])


def test_database_failure_is_safe_service_unavailable(client, visit, inputs, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from backend.app.services.clinical_integration import read_only
    def unavailable(*args, **kwargs):
        raise OperationalError("secret clinical SQL", {}, Exception("sensitive source"))
    monkeypatch.setattr(read_only.PhysicianCopilotService, "get_snapshot", unavailable)
    response = client.get(url(visit))
    assert response.status_code == 503
    assert "secret" not in response.text and "sensitive" not in response.text


def test_source_model_review_changes_invalidate_semantic_hash(client, visit, inputs, physician):
    first = client.get(url(visit)).json()
    adapter = MutableAdapter("imaging")
    adapter.version = "2.0.0"
    app.dependency_overrides[get_integration_adapters] = lambda: {**local_adapters(), "imaging": adapter}
    changed_model = client.get(url(visit)).json()
    assert first["snapshot_sha256"] != changed_model["snapshot_sha256"]
    add_report(client, visit, physician, key="EXTRA-CLINICAL", imaging=False)
    changed_source = client.get(url(visit)).json()
    assert changed_model["snapshot_sha256"] != changed_source["snapshot_sha256"]
    assert changed_source["safety_status"]["status"] == "stale"


def test_safety_alerts_self_contained_and_not_overridden(client, visit, inputs, physician):
    from backend.tests.test_clinical_safety import approve_rule, create_rule, rule_payload
    payload = rule_payload(inputs["fact"]["id"])
    payload["predicate"] = {"combinator": "all", "conditions": [{
        "source": "intake", "field": "exam_findings", "operator": "contains_text", "value": "Synthetic",
    }]}
    rule = create_rule(client, payload)
    approve_rule(client, rule["id"], physician)
    evaluate(client, visit)
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["safety_status"]["status"] == "alerts_present"
    assert data["safety_status"]["alerts"][0]["rule_id"] == rule["id"]
    assert "safety_alerts_require_review" in data["review_requirements"]
    assert data["is_clinical_clearance"] is False


def test_selected_evidence_requires_current_registry_approval(client, visit, inputs, physician):
    copilot = client.get(f"/api/v1/visits/{visit['id']}/physician-copilot").json()
    brief = client.post(f"/api/v1/visits/{visit['id']}/evidence-briefs", headers=physician, json={
        "clinical_question": "Synthetic clinician selected evidence review.",
        "expected_clinical_context_sha256": copilot["manifest"]["clinical_context_sha256"],
        "facts": [{"fact_id": inputs["fact"]["id"], "expected_content_sha256": inputs["fact"]["content_sha256"]}],
    })
    assert brief.status_code == 201, brief.text
    first = client.get(url(visit)).json()
    assert first["result"]["knowledge"][0]["fact_id"] == inputs["fact"]["id"]
    assert client.post(f"/api/v1/knowledge/facts/{inputs['fact']['id']}/retire", headers=physician).status_code == 200
    response = client.get(url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["result"]["knowledge"] == []
    assert "selected_knowledge_no_longer_valid" in data["review_requirements"]
    assert data["snapshot_sha256"] != first["snapshot_sha256"]


def test_corrupt_source_fails_with_safe_error(client, visit, inputs, db_session):
    db_session.execute(update(ParaclinicalReport).where(ParaclinicalReport.id == inputs["report"]["id"])
                       .values(content_sha256="0" * 64))
    db_session.commit()
    response = client.get(url(visit))
    assert response.status_code == 409
    assert "Synthetic" not in response.text


def test_disabled_unauthenticated_wrong_role_and_missing_visit(client, visit, monkeypatch):
    monkeypatch.setattr(settings, "CLINICAL_INTEGRATION_ENABLED", False)
    assert client.get(url(visit)).status_code == 404
    monkeypatch.setattr(settings, "CLINICAL_INTEGRATION_ENABLED", True)
    assert client.get(url({"id": "missing"})).status_code == 404
    receptionist = create_role_headers(client, username="intelligence_operator", role="operator")
    assert client.get(url(visit), headers=receptionist).status_code == 403
    client.headers.clear()
    assert client.get(url(visit)).status_code == 401


def test_dependency_change_during_composition_returns_conflict(client, visit, inputs, monkeypatch):
    from backend.app.services.clinical_integration import read_only
    original = read_only.PhysicianCopilotService.get_snapshot
    count = 0
    def changing(db, visit_id):
        nonlocal count
        result = original(db, visit_id)
        count += 1
        return result if count == 1 else result.model_copy(update={"snapshot_sha256": "f" * 64})
    monkeypatch.setattr(read_only.PhysicianCopilotService, "get_snapshot", changing)
    assert client.get(url(visit)).status_code == 409


def test_safety_review_change_is_detected_even_with_same_copilot_digest(client, visit, inputs, physician, monkeypatch):
    from backend.tests.test_clinical_safety import approve_rule, create_rule, rule_payload
    from backend.app.services.clinical_integration import read_only
    payload = rule_payload(inputs["fact"]["id"])
    payload["predicate"] = {"combinator": "all", "conditions": [{
        "source": "intake", "field": "exam_findings", "operator": "contains_text", "value": "Synthetic",
    }]}
    rule = create_rule(client, payload)
    approve_rule(client, rule["id"], physician)
    evaluate(client, visit)
    original = read_only.PhysicianCopilotService.get_snapshot
    count = 0
    def changing(db, visit_id):
        nonlocal count
        result = original(db, visit_id).model_copy(deep=True)
        count += 1
        if count > 1:
            result.safety_inbox.findings[0].timeline.review_status = "acknowledged"
        return result
    monkeypatch.setattr(read_only.PhysicianCopilotService, "get_snapshot", changing)
    assert client.get(url(visit)).status_code == 409


def test_published_snapshot_and_decision_schemas_match_producer_contract():
    from pathlib import Path
    from backend.app.schemas.clinical_decision_exchange import DecisionModelResult
    root = Path(__file__).resolve().parents[2]
    for name, model in (("snapshot", IntegratedClinicalSnapshot), ("decision", DecisionModelResult)):
        published = json.loads((root / f"docs/contracts/unified-clinical-{name}-1.0.0.schema.json").read_text())
        assert published == model.model_json_schema()


def test_three_mock_knee_mri_snapshot_is_repeatable_and_model_unverified():
    from backend.tools.clinical_intelligence_demo import synthetic_snapshot
    snapshot = synthetic_snapshot()
    assert snapshot == synthetic_snapshot()
    assert snapshot.result.workflow_state == "blocked"
    assert snapshot.result.unreviewed_findings[0].core == "imaging"
    assert snapshot.decision_model_reference.result.review_status == "unverified"
    assert snapshot.snapshot_sha256 == snapshot_digest(snapshot)
    assert snapshot.authorizes_treatment is snapshot.is_diagnosis is False
