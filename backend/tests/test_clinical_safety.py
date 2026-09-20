from copy import deepcopy

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from backend.app.models.clinical_safety import (
    ClinicalSafetyEvaluation,
    ClinicalSafetyFinding,
    ClinicalSafetyRule,
)
from backend.app.models.clinical_safety_review import (
    ClinicalSafetyFindingReview,
)
from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.repositories.audit_log import AuditLogRepository


pytestmark = pytest.mark.usefixtures("authenticated_admin")


def create_role_headers(client, *, username: str, role: str) -> dict[str, str]:
    created = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "password": "StrongPass123",
            "role": role,
        },
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "StrongPass123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def reviewer_headers(client):
    return create_role_headers(
        client,
        username="safety_reviewer",
        role="physician",
    )


@pytest.fixture
def nurse_headers(client):
    return create_role_headers(
        client,
        username="safety_nurse",
        role="nurse",
    )


@pytest.fixture
def visit(client):
    patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "SAFETY-001",
            "first_name": "Safety",
            "last_name": "Fixture",
            "date_of_birth": "1984-01-02",
        },
    )
    assert patient.status_code == 201, patient.text
    response = client.post(
        f"/api/v1/patients/{patient.json()['id']}/visits",
        json={"chief_complaint": "Synthetic knee complaint", "body_region": "knee"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def knowledge_payload(*, fact_key: str = "SAFETY-EVIDENCE-001") -> dict:
    return {
        "fact_key": fact_key,
        "title": "Synthetic safety evidence",
        "statement": (
            "This source-linked synthetic evidence statement exists only for "
            "testing the governed deterministic clinical safety engine."
        ),
        "clinical_domain": "clinical safety testing",
        "therapy_type": None,
        "population": "Synthetic test population.",
        "indication": "Automated test governance only.",
        "contraindications": [],
        "evidence_grade": "ungraded",
        "valid_from": "2026-01-01",
        "sources": [
            {
                "source_type": "guideline",
                "title": "Synthetic clinical safety guideline",
                "citation": "Synthetic citation used by automated tests only.",
                "publisher": "4B-MOS Test Suite",
                "url": "https://example.test/safety-guideline",
                "publication_date": "2025-01-01",
                "guideline_version": "1.0",
                "accessed_at": "2026-09-20",
            }
        ],
    }


def create_approved_fact(client, reviewer_headers, *, fact_key="SAFETY-EVIDENCE-001"):
    created = client.post(
        "/api/v1/knowledge/facts",
        json=knowledge_payload(fact_key=fact_key),
    )
    assert created.status_code == 201, created.text
    fact = created.json()
    assert client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/submit"
    ).status_code == 200
    reviewed = client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/review",
        json={"decision": "approved", "comment": "Synthetic evidence approved."},
        headers=reviewer_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()


def rule_payload(fact_id: str, **overrides) -> dict:
    payload = {
        "rule_key": "KNEE-SAFETY-001",
        "title": "Synthetic combined safety signal",
        "description": (
            "A deterministic synthetic rule used to verify intake and laboratory "
            "condition evaluation without issuing a diagnosis or prescription."
        ),
        "clinical_domain": "clinical safety testing",
        "severity": "high",
        "action": "review_before_proceeding",
        "message": "A physician must review this synthetic safety signal.",
        "predicate": {
            "combinator": "all",
            "conditions": [
                {
                    "source": "intake",
                    "field": "red_flags",
                    "operator": "contains_any",
                    "value": ["persistent fever"],
                },
                {
                    "source": "observation",
                    "field": "quantity_value",
                    "operator": "lt",
                    "value": "10.0",
                    "code_system": "LOINC",
                    "code": "718-7",
                    "unit_code": "g/dL",
                },
            ],
        },
        "knowledge_fact_ids": [fact_id],
        "valid_from": "2026-01-01",
        "valid_to": None,
    }
    payload.update(overrides)
    return payload


def create_rule(client, payload: dict) -> dict:
    response = client.post("/api/v1/safety/rules", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def approve_rule(client, rule_id: str, reviewer_headers: dict) -> dict:
    submitted = client.post(f"/api/v1/safety/rules/{rule_id}/submit")
    assert submitted.status_code == 200, submitted.text
    reviewed = client.post(
        f"/api/v1/safety/rules/{rule_id}/review",
        json={"decision": "approved", "comment": "Synthetic rule approved."},
        headers=reviewer_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()


def intake_payload(**overrides) -> dict:
    payload = {
        "chief_complaint": "Synthetic progressive knee pain",
        "history_present_illness": "Synthetic history for safety engine testing.",
        "body_region": "knee",
        "laterality": "right",
        "pain_score": 7,
        "functional_limitations": ["Stairs"],
        "relevant_history": [],
        "current_medications": [],
        "allergies": [],
        "exam_findings": "Synthetic exam finding.",
        "red_flags": ["Persistent fever for synthetic testing"],
        "clinical_impression": "Synthetic clinician impression.",
        "care_goal": "Synthetic mobility goal.",
    }
    payload.update(overrides)
    return payload


def report_payload(**observation_overrides) -> dict:
    observation = {
        "category": "laboratory",
        "code_system": "LOINC",
        "code": "718-7",
        "display_name": "Hemoglobin [Mass/volume] in Blood",
        "value_type": "quantity",
        "quantity_value": "8.500000",
        "unit_code": "g/dL",
        "unit_display": "grams per deciliter",
        "interpretation": "low",
    }
    observation.update(observation_overrides)
    return {
        "report_key": "SAFETY-LAB-001",
        "category": "laboratory",
        "title": "Synthetic safety laboratory report",
        "conclusion": "Synthetic report for deterministic rule testing.",
        "observations": [observation],
    }


def create_context(client, visit_id: str, *, finalize=True, **observation_overrides):
    intake = client.post(
        f"/api/v1/visits/{visit_id}/clinical-intakes",
        json=intake_payload(),
    )
    assert intake.status_code == 201, intake.text
    report = client.post(
        f"/api/v1/visits/{visit_id}/paraclinical-reports",
        json=report_payload(**observation_overrides),
    )
    assert report.status_code == 201, report.text
    if finalize:
        assert client.post(
            f"/api/v1/clinical-intakes/{intake.json()['id']}/finalize"
        ).status_code == 200
        assert client.post(
            f"/api/v1/paraclinical-reports/{report.json()['id']}/finalize"
        ).status_code == 200
    return intake.json(), report.json()


def test_rule_requires_current_approved_knowledge(
    client,
    reviewer_headers,
):
    draft = client.post(
        "/api/v1/knowledge/facts",
        json=knowledge_payload(),
    ).json()
    response = client.post(
        "/api/v1/safety/rules",
        json=rule_payload(draft["id"]),
    )
    assert response.status_code == 409
    assert "approved, currently valid" in response.json()["detail"]

    assert client.post(
        f"/api/v1/knowledge/facts/{draft['id']}/submit"
    ).status_code == 200
    assert client.post(
        f"/api/v1/knowledge/facts/{draft['id']}/review",
        json={"decision": "approved"},
        headers=reviewer_headers,
    ).status_code == 200
    rule = create_rule(client, rule_payload(draft["id"]))
    assert rule["status"] == "draft"
    assert rule["knowledge_links"][0]["medical_knowledge_fact_id"] == draft["id"]
    assert len(rule["content_sha256"]) == 64


@pytest.mark.parametrize(
    "condition",
    [
        {
            "source": "intake",
            "field": "__class__",
            "operator": "eq",
            "value": "unsafe",
        },
        {
            "source": "observation",
            "field": "quantity_value",
            "operator": "lt",
            "value": 10,
            "code_system": "LOINC",
            "code": "718-7",
        },
        {
            "source": "intake",
            "field": "pain_score",
            "operator": "between",
            "value": [9, 2],
        },
        {
            "source": "intake",
            "field": "red_flags",
            "operator": "contains_any",
            "value": ["fever"],
            "expression": "__import__('os').system('unsafe')",
        },
    ],
)
def test_rule_dsl_rejects_unsupported_or_executable_content(
    client,
    reviewer_headers,
    condition,
):
    fact = create_approved_fact(client, reviewer_headers)
    payload = rule_payload(fact["id"])
    payload["predicate"] = {"combinator": "all", "conditions": [condition]}
    response = client.post("/api/v1/safety/rules", json=payload)
    assert response.status_code == 422


def test_rule_needs_independent_review_and_exposes_only_approved(
    client,
    reviewer_headers,
):
    fact = create_approved_fact(client, reviewer_headers)
    rule = create_rule(client, rule_payload(fact["id"]))
    assert client.get("/api/v1/safety/rules/active").json() == []
    assert client.post(f"/api/v1/safety/rules/{rule['id']}/submit").status_code == 200

    self_review = client.post(
        f"/api/v1/safety/rules/{rule['id']}/review",
        json={"decision": "approved"},
    )
    assert self_review.status_code == 403
    approved = client.post(
        f"/api/v1/safety/rules/{rule['id']}/review",
        json={"decision": "approved"},
        headers=reviewer_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    active = client.get("/api/v1/safety/rules/active")
    assert [item["id"] for item in active.json()] == [rule["id"]]


def test_deterministic_evaluation_is_cited_explainable_and_append_only(
    client,
    visit,
    reviewer_headers,
):
    fact = create_approved_fact(client, reviewer_headers)
    rule = create_rule(client, rule_payload(fact["id"]))
    approve_rule(client, rule["id"], reviewer_headers)
    intake, report = create_context(client, visit["id"])

    response = client.post(f"/api/v1/visits/{visit['id']}/safety-evaluations")
    assert response.status_code == 201, response.text
    evaluation = response.json()
    assert evaluation["outcome"] == "alerts_present"
    assert evaluation["evaluated_rule_count"] == 1
    assert evaluation["triggered_count"] == 1
    assert evaluation["highest_severity"] == "high"
    assert evaluation["is_clinical_clearance"] is False
    assert evaluation["intake_id"] == intake["id"]
    assert evaluation["report_ids"] == [report["id"]]
    assert len(evaluation["clinical_context_sha256"]) == 64
    assert len(evaluation["rule_set_sha256"]) == 64
    assert len(evaluation["result_sha256"]) == 64

    finding = evaluation["findings"][0]
    assert finding["rule_id"] == rule["id"]
    assert finding["knowledge_fact_ids"] == [fact["id"]]
    assert [trace["matched"] for trace in finding["condition_trace"]] == [
        True,
        True,
    ]
    assert finding["condition_trace"][0]["matched_record_ids"] == [intake["id"]]
    assert finding["condition_trace"][1]["matched_record_ids"]

    second = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations",
        json={
            "expected_clinical_context_sha256": evaluation[
                "clinical_context_sha256"
            ],
            "expected_rule_set_sha256": evaluation["rule_set_sha256"],
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] != evaluation["id"]
    history = client.get(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    ).json()
    assert len(history) == 2


def test_drafts_are_excluded_and_no_rules_is_not_clearance(
    client,
    visit,
):
    create_context(client, visit["id"], finalize=False)
    response = client.post(f"/api/v1/visits/{visit['id']}/safety-evaluations")
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["outcome"] == "no_active_rules"
    assert result["intake_id"] is None
    assert result["report_ids"] == []
    assert result["findings"] == []
    assert result["is_clinical_clearance"] is False


def test_unit_mismatch_does_not_trigger_numeric_rule(
    client,
    visit,
    reviewer_headers,
):
    fact = create_approved_fact(client, reviewer_headers)
    rule = create_rule(client, rule_payload(fact["id"]))
    approve_rule(client, rule["id"], reviewer_headers)
    create_context(
        client,
        visit["id"],
        quantity_value="5.000000",
        unit_code="mmol/L",
        unit_display="millimoles per liter",
    )
    result = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    ).json()
    assert result["outcome"] == "no_alerts"
    assert result["triggered_count"] == 0


def test_missing_observation_rule_is_explicit_and_deterministic(
    client,
    visit,
    reviewer_headers,
):
    fact = create_approved_fact(client, reviewer_headers)
    payload = rule_payload(
        fact["id"],
        rule_key="MISSING-SAFETY-001",
        severity="warning",
        predicate={
            "combinator": "any",
            "conditions": [
                {
                    "source": "observation",
                    "field": "existence",
                    "operator": "is_missing",
                    "code_system": "LOINC",
                    "code": "777-3",
                }
            ],
        },
    )
    rule = create_rule(client, payload)
    approve_rule(client, rule["id"], reviewer_headers)
    intake = client.post(
        f"/api/v1/visits/{visit['id']}/clinical-intakes",
        json=intake_payload(red_flags=[]),
    ).json()
    assert client.post(
        f"/api/v1/clinical-intakes/{intake['id']}/finalize"
    ).status_code == 200
    result = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    ).json()
    assert result["outcome"] == "alerts_present"
    trace = result["findings"][0]["condition_trace"][0]
    assert trace["matched"] is True
    assert trace["matched_record_ids"] == []


def test_expected_hash_rejects_stale_evaluation_request(client, visit):
    response = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations",
        json={"expected_clinical_context_sha256": "0" * 64},
    )
    assert response.status_code == 409
    assert "clinical context changed" in response.json()["detail"]


def test_rule_supersession_retires_old_version_only_on_approval(
    client,
    reviewer_headers,
):
    fact = create_approved_fact(client, reviewer_headers)
    original_payload = rule_payload(fact["id"])
    original = create_rule(client, original_payload)
    original = approve_rule(client, original["id"], reviewer_headers)

    replacement_payload = deepcopy(original_payload)
    replacement_payload.pop("rule_key")
    replacement_payload["message"] = "A revised synthetic physician review is required."
    replacement = client.post(
        f"/api/v1/safety/rules/{original['id']}/supersede",
        json=replacement_payload,
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["version"] == 2
    assert client.get(f"/api/v1/safety/rules/{original['id']}").json()[
        "status"
    ] == "approved"

    replacement_id = replacement.json()["id"]
    approve_rule(client, replacement_id, reviewer_headers)
    assert client.get(f"/api/v1/safety/rules/{original['id']}").json()[
        "status"
    ] == "retired"
    active = client.get("/api/v1/safety/rules/active").json()
    assert [(item["rule_key"], item["version"]) for item in active] == [
        (original["rule_key"], 2)
    ]


def test_retired_evidence_fails_closed_instead_of_using_stale_rule(
    client,
    visit,
    reviewer_headers,
):
    fact = create_approved_fact(client, reviewer_headers)
    rule = create_rule(client, rule_payload(fact["id"]))
    approve_rule(client, rule["id"], reviewer_headers)
    create_context(client, visit["id"])
    retired = client.post(f"/api/v1/knowledge/facts/{fact['id']}/retire")
    assert retired.status_code == 200, retired.text

    evaluation = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    )
    assert evaluation.status_code == 409
    assert "not current" in evaluation.json()["detail"]


def test_rule_and_evaluation_integrity_tampering_is_detected(
    client,
    visit,
    reviewer_headers,
    db_session,
):
    fact = create_approved_fact(client, reviewer_headers)
    rule = create_rule(client, rule_payload(fact["id"]))
    approve_rule(client, rule["id"], reviewer_headers)
    create_context(client, visit["id"])
    evaluation = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    ).json()

    db_session.execute(
        update(ClinicalSafetyFinding)
        .where(ClinicalSafetyFinding.evaluation_id == evaluation["id"])
        .values(message="Tampered finding")
    )
    db_session.commit()
    detected = client.get(f"/api/v1/safety/evaluations/{evaluation['id']}")
    assert detected.status_code == 409
    assert "integrity check" in detected.json()["detail"]

    db_session.execute(
        update(ClinicalSafetyRule)
        .where(ClinicalSafetyRule.id == rule["id"])
        .values(message="Tampered rule")
    )
    db_session.commit()
    rule_detected = client.get(f"/api/v1/safety/rules/{rule['id']}")
    assert rule_detected.status_code == 409
    assert "integrity check" in rule_detected.json()["detail"]


def test_roles_restrict_evaluation_but_allow_clinical_read(
    client,
    visit,
    nurse_headers,
):
    result = client.post(f"/api/v1/visits/{visit['id']}/safety-evaluations")
    assert result.status_code == 201, result.text
    evaluation_id = result.json()["id"]
    assert client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations",
        headers=nurse_headers,
    ).status_code == 403
    assert client.get(
        f"/api/v1/safety/evaluations/{evaluation_id}",
        headers=nurse_headers,
    ).status_code == 200
    assert client.post(
        "/api/v1/safety/rules",
        json={},
        headers=nurse_headers,
    ).status_code == 403


def test_evaluation_write_and_audit_are_atomic(
    client,
    visit,
    db_session,
    monkeypatch,
):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic safety audit outage")

    monkeypatch.setattr(AuditLogRepository, "create", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic safety audit outage"):
        client.post(f"/api/v1/visits/{visit['id']}/safety-evaluations")
    assert db_session.query(ClinicalSafetyEvaluation).count() == 0


def test_audit_events_do_not_duplicate_patient_values(
    client,
    visit,
):
    create_context(client, visit["id"])
    evaluation = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    ).json()
    events = client.get(
        f"/api/v1/safety/evaluations/{evaluation['id']}/audit-logs"
    )
    assert events.status_code == 200
    assert "Persistent fever" not in events.text
    assert "8.500000" not in events.text
    assert "clinical_context_sha256" in events.text


def test_database_constraints_reject_invalid_rule_state(
    client,
    reviewer_headers,
    db_session,
):
    fact = create_approved_fact(client, reviewer_headers)
    rule = create_rule(client, rule_payload(fact["id"]))
    with pytest.raises(IntegrityError):
        db_session.execute(
            update(ClinicalSafetyRule)
            .where(ClinicalSafetyRule.id == rule["id"])
            .values(status="unsupported")
        )
        db_session.commit()
    db_session.rollback()


def test_unknown_safety_resources_are_404(client):
    assert client.get("/api/v1/safety/rules/missing").status_code == 404
    assert client.get("/api/v1/safety/evaluations/missing").status_code == 404
    assert client.get(
        "/api/v1/visits/missing/safety-evaluations"
    ).status_code == 404


def test_patient_records_never_promote_themselves_to_rules_or_knowledge(
    client,
    visit,
    db_session,
):
    create_context(client, visit["id"])
    client.post(f"/api/v1/visits/{visit['id']}/safety-evaluations")
    assert db_session.query(ClinicalSafetyRule).count() == 0
    assert db_session.query(MedicalKnowledgeFact).count() == 0


def create_reviewable_finding(client, reviewer_headers, visit) -> dict:
    fact = create_approved_fact(
        client,
        reviewer_headers,
        fact_key=f"SAFETY-REVIEW-{visit['id'][:8]}",
    )
    rule = create_rule(
        client,
        rule_payload(
            fact["id"],
            rule_key=f"REVIEW-{visit['id'][:8]}",
        ),
    )
    approve_rule(client, rule["id"], reviewer_headers)
    create_context(client, visit["id"])
    evaluation = client.post(
        f"/api/v1/visits/{visit['id']}/safety-evaluations"
    )
    assert evaluation.status_code == 201, evaluation.text
    data = evaluation.json()
    assert data["outcome"] == "alerts_present"
    return {
        "evaluation": data,
        "finding": data["findings"][0],
    }


def test_finding_review_starts_unreviewed_and_is_snapshot_bound(
    client,
    visit,
    reviewer_headers,
    nurse_headers,
):
    reviewable = create_reviewable_finding(client, reviewer_headers, visit)
    evaluation = reviewable["evaluation"]
    finding = reviewable["finding"]
    path = (
        f"/api/v1/visits/{visit['id']}/safety-findings/"
        f"{finding['id']}/reviews"
    )

    initial = client.get(path, headers=nurse_headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["review_status"] == "unreviewed"
    assert initial.json()["reviews"] == []
    assert initial.json()["is_clinical_clearance"] is False
    assert initial.json()["changes_evaluation_result"] is False

    missing_hash = client.post(
        path,
        json={"action": "acknowledged"},
        headers=nurse_headers,
    )
    assert missing_hash.status_code == 422

    stale = client.post(
        path,
        json={
            "action": "acknowledged",
            "expected_evaluation_result_sha256": "0" * 64,
        },
        headers=nurse_headers,
    )
    assert stale.status_code == 409
    assert "reload" in stale.json()["detail"]

    recorded = client.post(
        path,
        json={
            "action": "acknowledged",
            "expected_evaluation_result_sha256": evaluation["result_sha256"],
        },
        headers=nurse_headers,
    )
    assert recorded.status_code == 201, recorded.text
    timeline = recorded.json()
    assert timeline["review_status"] == "acknowledged"
    assert timeline["is_clinical_clearance"] is False
    assert timeline["changes_evaluation_result"] is False
    review = timeline["reviews"][0]
    assert review["sequence"] == 1
    assert review["previous_review_sha256"] is None
    assert review["payload"]["actor"]["actor_role"] == "nurse"
    assert review["payload"]["evaluation_result_sha256"] == evaluation[
        "result_sha256"
    ]
    assert len(review["sha256"]) == 64

    fetched = client.get(
        f"/api/v1/safety/finding-reviews/{review['id']}",
        headers=nurse_headers,
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == review


def test_review_transition_is_append_only_and_assessment_is_physician_only(
    client,
    visit,
    reviewer_headers,
    nurse_headers,
):
    reviewable = create_reviewable_finding(client, reviewer_headers, visit)
    evaluation = reviewable["evaluation"]
    finding = reviewable["finding"]
    path = (
        f"/api/v1/visits/{visit['id']}/safety-findings/"
        f"{finding['id']}/reviews"
    )
    base = {"expected_evaluation_result_sha256": evaluation["result_sha256"]}

    acknowledged = client.post(
        path,
        json={**base, "action": "acknowledged"},
        headers=nurse_headers,
    )
    assert acknowledged.status_code == 201, acknowledged.text
    first = acknowledged.json()["reviews"][0]

    duplicate = client.post(
        path,
        json={**base, "action": "acknowledged"},
        headers=nurse_headers,
    )
    assert duplicate.status_code == 409

    missing_note = client.post(
        path,
        json={**base, "action": "escalated"},
        headers=nurse_headers,
    )
    assert missing_note.status_code == 422

    escalated = client.post(
        path,
        json={
            **base,
            "action": "escalated",
            "note": "Escalated for prompt physician assessment.",
        },
        headers=nurse_headers,
    )
    assert escalated.status_code == 201, escalated.text
    second = escalated.json()["reviews"][1]
    assert second["sequence"] == 2
    assert second["previous_review_sha256"] == first["sha256"]

    nurse_assessment = client.post(
        path,
        json={
            **base,
            "action": "assessed",
            "disposition": "requires_action",
            "reason_code": "clinical_context",
            "note": "Synthetic nurse assessment must be refused.",
        },
        headers=nurse_headers,
    )
    assert nurse_assessment.status_code == 403

    incomplete_assessment = client.post(
        path,
        json={**base, "action": "assessed"},
        headers=reviewer_headers,
    )
    assert incomplete_assessment.status_code == 422

    assessed = client.post(
        path,
        json={
            **base,
            "action": "assessed",
            "disposition": "action_documented",
            "reason_code": "action_taken",
            "note": (
                "Synthetic physician assessment documented for workflow testing; "
                "this does not grant clinical clearance."
            ),
        },
        headers=reviewer_headers,
    )
    assert assessed.status_code == 201, assessed.text
    timeline = assessed.json()
    assert timeline["review_status"] == "assessed"
    assert [item["action"] for item in timeline["reviews"]] == [
        "acknowledged",
        "escalated",
        "assessed",
    ]
    assert timeline["reviews"][2]["previous_review_sha256"] == second["sha256"]
    assert timeline["reviews"][2]["is_clinical_clearance"] is False

    terminal = client.post(
        path,
        json={
            **base,
            "action": "escalated",
            "note": "A terminal assessment cannot be rewritten.",
        },
        headers=nurse_headers,
    )
    assert terminal.status_code == 409


def test_review_events_are_audited_without_patient_values(
    client,
    visit,
    reviewer_headers,
    nurse_headers,
):
    reviewable = create_reviewable_finding(client, reviewer_headers, visit)
    evaluation = reviewable["evaluation"]
    finding = reviewable["finding"]
    path = (
        f"/api/v1/visits/{visit['id']}/safety-findings/"
        f"{finding['id']}"
    )
    recorded = client.post(
        f"{path}/reviews",
        json={
            "action": "escalated",
            "expected_evaluation_result_sha256": evaluation["result_sha256"],
            "note": "Synthetic escalation without duplicated patient values.",
        },
        headers=nurse_headers,
    )
    assert recorded.status_code == 201, recorded.text

    events = client.get(f"{path}/audit-logs", headers=nurse_headers)
    assert events.status_code == 200, events.text
    event = events.json()[-1]
    assert event["event_type"] == "clinical_safety_finding_escalated"
    assert event["to_state"] == "escalated"
    assert event["event_data"]["is_clinical_clearance"] is False
    assert "Persistent fever" not in events.text
    assert "8.500000" not in events.text
    assert "Synthetic escalation" not in events.text


def test_tampered_review_chain_is_rejected(
    client,
    visit,
    reviewer_headers,
    nurse_headers,
    db_session,
):
    reviewable = create_reviewable_finding(client, reviewer_headers, visit)
    evaluation = reviewable["evaluation"]
    finding = reviewable["finding"]
    path = (
        f"/api/v1/visits/{visit['id']}/safety-findings/"
        f"{finding['id']}/reviews"
    )
    recorded = client.post(
        path,
        json={
            "action": "acknowledged",
            "expected_evaluation_result_sha256": evaluation["result_sha256"],
        },
        headers=nurse_headers,
    )
    assert recorded.status_code == 201, recorded.text
    review_id = recorded.json()["reviews"][0]["id"]

    db_session.execute(
        update(ClinicalSafetyFindingReview)
        .where(ClinicalSafetyFindingReview.id == review_id)
        .values(payload={"schema_version": 1, "tampered": True})
    )
    db_session.commit()
    response = client.get(path, headers=nurse_headers)
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"]


def test_finding_review_rows_reject_orm_update_and_delete(
    client,
    visit,
    reviewer_headers,
    nurse_headers,
    db_session,
):
    reviewable = create_reviewable_finding(client, reviewer_headers, visit)
    evaluation = reviewable["evaluation"]
    finding = reviewable["finding"]
    path = (
        f"/api/v1/visits/{visit['id']}/safety-findings/"
        f"{finding['id']}/reviews"
    )
    recorded = client.post(
        path,
        json={
            "action": "acknowledged",
            "expected_evaluation_result_sha256": evaluation["result_sha256"],
        },
        headers=nurse_headers,
    )
    assert recorded.status_code == 201, recorded.text
    review_id = recorded.json()["reviews"][0]["id"]

    review = db_session.get(ClinicalSafetyFindingReview, review_id)
    review.action = "escalated"
    with pytest.raises(ValueError, match="cannot be updated or deleted"):
        db_session.commit()
    db_session.rollback()

    review = db_session.get(ClinicalSafetyFindingReview, review_id)
    db_session.delete(review)
    with pytest.raises(ValueError, match="cannot be updated or deleted"):
        db_session.commit()
    db_session.rollback()


def test_finding_review_access_and_visit_scope(
    client,
    visit,
    reviewer_headers,
    nurse_headers,
):
    reviewable = create_reviewable_finding(client, reviewer_headers, visit)
    evaluation = reviewable["evaluation"]
    finding = reviewable["finding"]
    viewer_headers = create_role_headers(
        client,
        username="safety_review_viewer",
        role="viewer",
    )
    path = (
        f"/api/v1/visits/{visit['id']}/safety-findings/"
        f"{finding['id']}/reviews"
    )
    assert client.get(path, headers=viewer_headers).status_code == 403
    assert client.get(path).status_code == 200
    assert client.post(
        path,
        json={
            "action": "acknowledged",
            "expected_evaluation_result_sha256": evaluation["result_sha256"],
        },
    ).status_code == 403

    other_patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "SAFETY-OTHER",
            "first_name": "Other",
            "last_name": "Visit",
        },
    ).json()
    other_visit = client.post(
        f"/api/v1/patients/{other_patient['id']}/visits",
        json={"chief_complaint": "Other synthetic complaint"},
    ).json()
    wrong_scope = client.get(
        f"/api/v1/visits/{other_visit['id']}/safety-findings/"
        f"{finding['id']}/reviews",
        headers=nurse_headers,
    )
    assert wrong_scope.status_code == 404
