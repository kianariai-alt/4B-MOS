"""Isolated SQLite/API integration; all records and producer outputs are synthetic."""

from copy import deepcopy
from datetime import timedelta
import json

import pytest
from sqlalchemy import select, update

from backend.app.api.routes.clinical_integration import get_integration_adapters
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_integration import ClinicalIntegrationRun, ClinicalIntegrationReview
from backend.app.schemas.clinical_integration import ComponentVersion
from backend.app.services.clinical_integration.adapters import FinalRecordAdapter, local_adapters
from backend.tests.test_medical_knowledge import approve_fact, create_fact
from backend.tests.test_physician_copilot import create_role_headers

pytestmark = pytest.mark.usefixtures("authenticated_admin")


@pytest.fixture(autouse=True)
def enable_preview(monkeypatch):
    monkeypatch.setattr(settings, "CLINICAL_INTEGRATION_ENABLED", True)


@pytest.fixture
def physician(client):
    return create_role_headers(client, username="integration_physician", role="physician")


@pytest.fixture
def visit(client):
    patient = client.post("/api/v1/patients", json={
        "patient_code": "INTEGRATION-SYNTHETIC", "first_name": "Synthetic", "last_name": "Fixture",
    })
    assert patient.status_code == 201, patient.text
    visit = client.post(f"/api/v1/patients/{patient.json()['id']}/visits", json={"body_region": "knee"})
    assert visit.status_code == 201, visit.text
    return visit.json()


def add_report(client, visit, physician, *, key="MRI-SYNTHETIC", imaging=True, value=True, finalize=True):
    response = client.post(f"/api/v1/visits/{visit['id']}/paraclinical-reports", json={
        "report_key": key, "category": "imaging" if imaging else "clinical_test",
        "title": "Synthetic structured report", "observations": [{
            "category": "imaging" if imaging else "clinical_test", "code_system": "LOCAL",
            "code": "SYNTHETIC_EFFUSION", "display_name": "Synthetic effusion finding",
            "value_type": "boolean", "boolean_value": value, "body_site": "left knee",
        }],
    })
    assert response.status_code == 201, response.text
    report = response.json()
    if finalize:
        response = client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize", headers=physician)
        assert response.status_code == 200, response.text
    return report


def evaluate(client, visit):
    response = client.post(f"/api/v1/visits/{visit['id']}/safety-evaluations", json={})
    assert response.status_code == 201, response.text


@pytest.fixture
def inputs(client, visit, physician):
    intake = client.post(f"/api/v1/visits/{visit['id']}/clinical-intakes", json={
        "chief_complaint": "Synthetic complaint", "history_present_illness": "Synthetic history only",
        "exam_findings": "Synthetic limited movement", "body_region": "knee", "laterality": "left",
    })
    assert intake.status_code == 201, intake.text
    response = client.post(f"/api/v1/clinical-intakes/{intake.json()['id']}/finalize", headers=physician)
    assert response.status_code == 200, response.text
    report = add_report(client, visit, physician)
    fact = approve_fact(client, create_fact(client)["id"], physician)
    evaluate(client, visit)
    return {"intake": intake.json(), "report": report, "fact": fact}


def create_run(client, visit, *, key="run-one", knowledge=()):
    context = client.get(f"/api/v1/visits/{visit['id']}/physician-copilot").json()
    return client.post(f"/api/v1/visits/{visit['id']}/clinical-integration/runs", json={
        "request_key": key, "expected_clinical_context_sha256": context["manifest"]["clinical_context_sha256"],
        "knowledge_fact_ids": list(knowledge),
    })


def run_url(visit, run):
    return f"/api/v1/visits/{visit['id']}/clinical-integration/runs/{run['id']}"


def review_body(run, *, action="approve_summary", key="review-one"):
    return {"request_key": key, "expected_result_sha256": run["result_sha256"],
            "action": action, "rationale": "Independent synthetic physician review."}


def test_valid_two_core_run_copilot_review_audit_and_replay(client, visit, inputs, physician, db_session):
    response = create_run(client, visit, knowledge=(inputs["fact"]["id"],))
    assert response.status_code == 201, response.text
    run = response.json()
    assert response.headers["Cache-Control"] == "no-store"
    result = run["result"]
    assert run["freshness"] == "current"
    assert result["workflow_state"] == "awaiting_physician_review"
    assert {item["core"] for item in result["confirmed_findings"]} == {"orthopedic", "imaging"}
    assert result["unreviewed_findings"] == []
    assert result["knowledge"][0]["applicability"] == "not_assessed"
    assert result["imaging_studies"][0]["dicom_identity_verified"] is False
    assert run["reviews"] == []
    assert create_run(client, visit, knowledge=(inputs["fact"]["id"],)).json() == run
    changed = create_run(client, visit)
    assert changed.status_code == 409
    reviewed = client.post(run_url(visit, run) + "/reviews", headers=physician, json=review_body(run))
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["authorizes_treatment"] is False
    assert client.post(run_url(visit, run) + "/reviews", headers=physician, json=review_body(run)).json() == reviewed.json()
    view = client.get(f"/api/v1/visits/{visit['id']}/physician-copilot/integration").json()
    assert view["latest_run"]["reviews"] == [reviewed.json()]
    assert view["latest_run"]["result"]["workflow_state"] == "awaiting_physician_review"
    assert view["is_clinical_clearance"] is False
    audit = client.get(run_url(visit, run) + "/audit-events")
    assert audit.status_code == 200
    assert {row["event_type"] for row in audit.json()} == {"integration_run_created", "integration_physician_reviewed"}
    logs = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "clinical_integration")).all()
    text = json.dumps([row.event_data for row in logs])
    assert "Synthetic limited movement" not in text
    assert "patient_id" not in text
    assert "rationale" not in text


def test_missing_core_and_unfinalized_imaging_are_visible_and_blocked(client, visit, inputs, physician):
    assert client.post(f"/api/v1/paraclinical-reports/{inputs['report']['id']}/entered-in-error",
                       json={"reason": "Synthetic incorrect report entry."}, headers=physician).status_code == 200
    add_report(client, visit, physician, key="DRAFT-IMAGE", finalize=False)
    evaluate(client, visit)
    response = create_run(client, visit)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["result"]["cores"][1]["status"] == "missing"
    assert not any(item["core"] == "imaging" for item in run["result"]["confirmed_findings"])
    assert run["result"]["workflow_state"] == "blocked"
    assert client.post(run_url(visit, run) + "/reviews", json=review_body(run), headers=physician).status_code == 409
    assert client.post(run_url(visit, run) + "/reviews", json=review_body(run, action="defer"), headers=physician).status_code == 201


def test_same_code_exam_imaging_contradiction_is_not_silently_reconciled(client, visit, inputs, physician):
    add_report(client, visit, physician, key="CLINICAL-EXAM", imaging=False, value=False)
    evaluate(client, visit)
    response = create_run(client, visit)
    assert response.status_code == 201, response.text
    result = response.json()["result"]
    assert "discordant_values_for_same_code_and_site" in {item["code"] for item in result["issues"]}
    assert len(result["confirmed_findings"]) == 3
    assert result["workflow_state"] == "blocked"


class MutableAdapter(FinalRecordAdapter):
    mode = "record"
    version = "1.0.0"

    def current_version(self):
        original = super().current_version()
        return ComponentVersion(**(original.model_dump() | {
            "version": self.version, "kind": "model" if self.mode == "model" else "adapter",
        }))

    def collect(self, context):
        if self.mode == "timeout":
            raise TimeoutError("secret-link?token=NEVER-LEAK Synthetic Patient")
        output = super().collect(context)
        if self.mode == "model":
            return output.model_copy(update={"findings": tuple(
                item.model_copy(update={"origin": "model", "confidence": 0.999}) for item in output.findings
            )})
        if self.mode == "forged":
            finding = output.findings[0]
            changed = finding.observation.model_copy(update={"boolean_value": False})
            return output.model_copy(update={"findings": (finding.model_copy(update={"observation": changed}),)})
        if self.mode == "wrong_visit":
            return output.model_copy(update={"visit_id": "a-different-visit"})
        if self.mode == "expired":
            return output.model_copy(update={"generated_at": output.generated_at - timedelta(days=2),
                                             "valid_until": output.valid_until - timedelta(days=2)})
        return output


@pytest.fixture
def adapters():
    imaging = MutableAdapter("imaging")
    collection = local_adapters() | {"imaging": imaging}
    app.dependency_overrides[get_integration_adapters] = lambda: collection
    return collection


@pytest.mark.parametrize("mode,issue", [
    ("model", "finding_requires_physician_review"), ("forged", "record_value_mismatch"),
    ("wrong_visit", "invalid_core_output"), ("timeout", "core_unavailable"),
    ("expired", "expired_core_output"),
])
def test_untrusted_model_invalid_sources_expiry_and_service_failure(client, visit, inputs, physician, adapters, mode, issue):
    adapters["imaging"].mode = mode
    response = create_run(client, visit)
    assert response.status_code == 201, response.text
    run = response.json()
    result = run["result"]
    assert issue in {item["code"] for item in result["issues"]}
    assert result["workflow_state"] == "blocked"
    assert not any(item["core"] == "imaging" for item in result["confirmed_findings"])
    if mode == "model":
        assert result["unreviewed_findings"][0]["review_status"] == "unreviewed_model"
        assert result["unreviewed_findings"][0]["approval"] is None
    assert "NEVER-LEAK" not in response.text
    assert client.post(run_url(visit, run) + "/reviews", json=review_body(run), headers=physician).status_code == 409
    if mode == "timeout":
        adapters["imaging"].mode = "record"
        replay = create_run(client, visit).json()
        assert replay["id"] == run["id"]  # Same request never silently reruns a producer.
        retry = create_run(client, visit, key="run-retry").json()
        assert retry["id"] != run["id"]
        assert retry["result"]["workflow_state"] == "awaiting_physician_review"


def test_component_version_changes_invalidate_saved_run(client, visit, inputs, physician, adapters):
    run = create_run(client, visit).json()
    adapters["imaging"].version = "2.0.0"
    read = client.get(run_url(visit, run)).json()
    assert read["freshness"] == "stale"
    assert "imaging_component_changed" in read["invalidation_reasons"]
    assert read["result_sha256"] == run["result_sha256"]
    assert client.post(run_url(visit, run) + "/reviews", json=review_body(run), headers=physician).status_code == 409


def test_knowledge_retirement_and_context_change_invalidate_without_rewrite(client, visit, inputs, physician):
    run = create_run(client, visit, knowledge=(inputs["fact"]["id"],)).json()
    retired = client.post(f"/api/v1/knowledge/facts/{inputs['fact']['id']}/retire",
                          json={"comment": "Synthetic retirement."}, headers=physician)
    assert retired.status_code == 200, retired.text
    read = client.get(run_url(visit, run)).json()
    assert read["freshness"] == "stale"
    assert "knowledge_no_longer_valid" in read["invalidation_reasons"]
    assert create_run(client, visit, key="new-run", knowledge=(inputs["fact"]["id"],)).status_code == 409
    marked = client.post(f"/api/v1/clinical-intakes/{inputs['intake']['id']}/entered-in-error",
                         json={"reason": "Synthetic clinical correction needed."}, headers=physician)
    assert marked.status_code == 200
    read = client.get(run_url(visit, run)).json()
    assert "clinical_context_changed" in read["invalidation_reasons"]
    assert read["result"] == run["result"]


@pytest.mark.parametrize("role", ["nurse", "operator", "viewer"])
def test_nonphysician_roles_cannot_access_integration(client, visit, inputs, role):
    headers = create_role_headers(client, username=f"integration_{role}", role=role)
    assert client.get(f"/api/v1/visits/{visit['id']}/physician-copilot/integration", headers=headers).status_code == 403
    assert client.get("/api/v1/clinical-integration/contract", headers=headers).status_code == 403


def test_admin_cannot_author_physician_review_and_feature_disabled_by_default(client, visit, inputs, monkeypatch):
    run = create_run(client, visit).json()
    assert client.post(run_url(visit, run) + "/reviews", json=review_body(run)).status_code == 403
    monkeypatch.setattr(settings, "CLINICAL_INTEGRATION_ENABLED", False)
    assert client.get(run_url(visit, run)).status_code == 404


def test_immutable_snapshot_tampering_detection_and_atomic_audit(client, visit, inputs, db_session):
    run = create_run(client, visit).json()
    stored = db_session.get(ClinicalIntegrationRun, run["id"])
    stored.result_sha256 = "f" * 64
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    stored = db_session.get(ClinicalIntegrationRun, run["id"])
    db_session.delete(stored)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    # Simulate privileged one-sided corruption, bypassing ORM hooks.
    payload = deepcopy(stored.payload)
    payload["result"]["visit"]["status"] = "cancelled"
    db_session.execute(update(ClinicalIntegrationRun).where(ClinicalIntegrationRun.id == run["id"]).values(payload=payload))
    db_session.commit()
    assert client.get(run_url(visit, run)).status_code == 409


def test_audit_failure_rolls_back_snapshot(client, visit, inputs, monkeypatch, db_session):
    from backend.app.repositories.audit_log import AuditLogRepository
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit unavailable")
    monkeypatch.setattr(AuditLogRepository, "create", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        create_run(client, visit)
    assert db_session.scalar(select(ClinicalIntegrationRun)) is None
    assert db_session.scalar(select(ClinicalIntegrationReview)) is None


def test_admin_finalized_imaging_is_not_treated_as_physician_confirmed(client, visit, inputs, physician):
    client.post(f"/api/v1/paraclinical-reports/{inputs['report']['id']}/entered-in-error",
                json={"reason": "Synthetic replacement requested."}, headers=physician)
    draft = add_report(client, visit, physician, key="ADMIN-ONLY-REVIEW", finalize=False)
    assert client.post(f"/api/v1/paraclinical-reports/{draft['id']}/finalize").status_code == 200
    evaluate(client, visit)
    run = create_run(client, visit).json()
    assert run["result"]["unreviewed_findings"][0]["review_status"] == "unreviewed_source"
    assert not any(item["core"] == "imaging" for item in run["result"]["confirmed_findings"])


def test_stale_context_guard_unknown_visit_cross_visit_and_unauthenticated_access(client, visit, inputs):
    response = client.post(f"/api/v1/visits/{visit['id']}/clinical-integration/runs", json={
        "request_key": "stale-guard", "expected_clinical_context_sha256": "0" * 64,
    })
    assert response.status_code == 409
    run = create_run(client, visit).json()
    assert client.get(run_url({"id": "nonexistent"}, run)).status_code == 404
    assert client.get(run_url(visit, {"id": "nonexistent"})).status_code == 404
    client.headers.clear()
    assert client.get(run_url(visit, run)).status_code == 401


def test_new_safety_rules_invalidate_prior_snapshot_and_require_new_evaluation(client, visit, inputs, physician):
    from backend.tests.test_clinical_safety import approve_rule, create_rule, rule_payload
    run = create_run(client, visit).json()
    rule = create_rule(client, rule_payload(inputs["fact"]["id"]))
    approve_rule(client, rule["id"], physician)
    read = client.get(run_url(visit, run)).json()
    assert "safety_rules_changed" in read["invalidation_reasons"]
    new = create_run(client, visit, key="after-new-rule").json()
    assert "safety_evaluation_stale" in {item["code"] for item in new["result"]["issues"]}
    assert new["result"]["workflow_state"] == "blocked"


def test_governed_knowledge_version_replacement_invalidates_reference(client, visit, inputs, physician):
    from backend.tests.test_medical_knowledge import knowledge_payload
    run = create_run(client, visit, knowledge=(inputs["fact"]["id"],)).json()
    content = knowledge_payload()
    del content["fact_key"]
    content["title"] = "Revised synthetic evidence version"
    response = client.post(f"/api/v1/knowledge/facts/{inputs['fact']['id']}/supersede", json=content)
    assert response.status_code == 201, response.text
    replacement = approve_fact(client, response.json()["id"], physician)
    assert replacement["version"] == 2
    read = client.get(run_url(visit, run)).json()
    assert read["freshness"] == "stale"
    assert "knowledge_no_longer_valid" in read["invalidation_reasons"]


def test_review_hash_idempotency_append_only_and_tamper_checks(client, visit, inputs, physician, db_session):
    run = create_run(client, visit).json()
    body = review_body(run)
    assert client.post(run_url(visit, run) + "/reviews", headers=physician,
                       json=body | {"expected_result_sha256": "0" * 64}).status_code == 409
    response = client.post(run_url(visit, run) + "/reviews", headers=physician, json=body)
    assert response.status_code == 201, response.text
    assert client.post(run_url(visit, run) + "/reviews", headers=physician,
                       json=body | {"action": "reject"}).status_code == 409
    row = db_session.get(ClinicalIntegrationReview, response.json()["id"])
    db_session.delete(row)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    row = db_session.get(ClinicalIntegrationReview, response.json()["id"])
    payload = deepcopy(row.payload)
    payload["action"] = "reject"
    db_session.execute(update(ClinicalIntegrationReview).where(ClinicalIntegrationReview.id == row.id).values(payload=payload))
    db_session.commit()
    assert client.get(run_url(visit, run)).status_code == 409


def test_core_payloads_minimize_identifiers_and_do_not_cross_feed_inputs(client, visit, inputs, adapters):
    observed = {}
    for name, adapter in adapters.items():
        collect = adapter.collect
        def capture(context, *, core=name, original=collect):
            observed[core] = context.model_dump(mode="json")
            return original(context)
        adapter.collect = capture
    assert create_run(client, visit).status_code == 201
    for core, context in observed.items():
        assert "patient_id" not in json.dumps(context)
        assert "first_name" not in json.dumps(context)
        assert all((item["observation"]["category"] == "imaging") == (core == "imaging")
                   for item in context["observations"])


def test_empty_visit_is_blocked_without_inventing_clinical_findings(client, visit):
    response = create_run(client, visit)
    assert response.status_code == 201, response.text
    result = response.json()["result"]
    assert result["confirmed_findings"] == result["unreviewed_findings"] == []
    assert {item["code"] for item in result["issues"]} >= {
        "core_missing", "safety_evaluation_missing", "final_clinical_assessment_missing",
    }


def test_review_window_expiry_is_visible_without_modifying_snapshot(client, visit, inputs, physician, monkeypatch):
    from backend.app.services.clinical_integration import service
    run = create_run(client, visit).json()
    original = service.datetime
    class FutureClock(original):
        @classmethod
        def now(cls, tz=None):
            return original.now(tz) + timedelta(days=2)
    monkeypatch.setattr(service, "datetime", FutureClock)
    read = client.get(run_url(visit, run)).json()
    assert read["freshness"] == "stale"
    assert "review_window_expired" in read["invalidation_reasons"]
    assert read["result_sha256"] == run["result_sha256"]
    assert client.post(run_url(visit, run) + "/reviews", headers=physician, json=review_body(run)).status_code == 409


def test_existing_clinician_selected_evidence_is_referenced_without_claiming_applicability(client, visit, inputs, physician):
    run = create_run(client, visit).json()
    context = client.get(f"/api/v1/visits/{visit['id']}/physician-copilot").json()
    response = client.post(f"/api/v1/visits/{visit['id']}/evidence-briefs", headers=physician, json={
        "clinical_question": "Synthetic evidence question for independent review.",
        "expected_clinical_context_sha256": context["manifest"]["clinical_context_sha256"],
        "facts": [{"fact_id": inputs["fact"]["id"], "expected_content_sha256": inputs["fact"]["content_sha256"]}],
    })
    assert response.status_code == 201, response.text
    historical = client.get(run_url(visit, run)).json()
    assert "copilot_dependencies_changed" in historical["invalidation_reasons"]
    current = create_run(client, visit, key="with-evidence").json()
    reference = current["result"]["evidence_briefs"][0]
    assert reference["brief_id"] == response.json()["id"]
    assert reference["context_matches"] is True
    assert reference["knowledge_status"] == "historical_snapshot_only"


def test_mixed_report_categories_are_flagged_instead_of_silently_dropped(client, visit, inputs, physician):
    response = client.post(f"/api/v1/visits/{visit['id']}/paraclinical-reports", json={
        "report_key": "MIXED-CATEGORY", "category": "other", "title": "Synthetic mixed report",
        "observations": [{"category": "imaging", "code_system": "LOCAL", "code": "MIXED",
                          "display_name": "Synthetic mixed finding", "value_type": "boolean", "boolean_value": True}],
    })
    assert response.status_code == 201
    assert client.post(f"/api/v1/paraclinical-reports/{response.json()['id']}/finalize", headers=physician).status_code == 200
    evaluate(client, visit)
    run = create_run(client, visit).json()
    assert "report_observation_category_mismatch" in {issue["code"] for issue in run["result"]["issues"]}
    assert run["result"]["workflow_state"] == "blocked"


def test_unavailable_safety_rule_evidence_fails_closed_without_raw_error_details(client, visit, inputs, physician):
    from backend.tests.test_clinical_safety import approve_rule, create_rule, rule_payload
    rule = create_rule(client, rule_payload(inputs["fact"]["id"]))
    approve_rule(client, rule["id"], physician)
    assert client.post(f"/api/v1/knowledge/facts/{inputs['fact']['id']}/retire", headers=physician).status_code == 200
    response = create_run(client, visit)
    assert response.status_code == 409
    assert inputs["fact"]["statement"] not in response.text
