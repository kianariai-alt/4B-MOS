from copy import deepcopy

import pytest
from sqlalchemy import update

from backend.app.models.clinical_evidence import ClinicalEvidenceBrief
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.clinical_context import ClinicalContextRead
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.session_finalization import evidence_digest


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
def physician_headers(client):
    return create_role_headers(
        client,
        username="evidence_physician",
        role="physician",
    )


@pytest.fixture
def nurse_headers(client):
    return create_role_headers(
        client,
        username="evidence_nurse",
        role="nurse",
    )


@pytest.fixture
def visit(client):
    patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "EVIDENCE-001",
            "first_name": "Evidence",
            "last_name": "Fixture",
            "date_of_birth": "1980-01-02",
        },
    )
    assert patient.status_code == 201, patient.text
    response = client.post(
        f"/api/v1/patients/{patient.json()['id']}/visits",
        json={"chief_complaint": "Synthetic evidence visit", "body_region": "knee"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def intake_payload() -> dict:
    return {
        "chief_complaint": "Synthetic progressive knee pain",
        "history_present_illness": "Synthetic history for evidence-brief testing.",
        "body_region": "knee",
        "laterality": "right",
        "pain_score": 6,
        "functional_limitations": ["Stairs"],
        "relevant_history": [],
        "current_medications": [],
        "allergies": [],
        "exam_findings": "Synthetic examination finding.",
        "red_flags": [],
        "clinical_impression": "Synthetic clinician impression.",
        "care_goal": "Synthetic mobility goal.",
    }


def report_payload() -> dict:
    return {
        "report_key": "EVIDENCE-LAB-001",
        "category": "laboratory",
        "title": "Synthetic evidence laboratory report",
        "conclusion": "Synthetic report for evidence-brief testing.",
        "observations": [
            {
                "category": "laboratory",
                "code_system": "LOINC",
                "code": "718-7",
                "display_name": "Synthetic hemoglobin",
                "value_type": "quantity",
                "quantity_value": "12.000000",
                "unit_code": "g/dL",
                "unit_display": "grams per deciliter",
                "interpretation": "normal",
            }
        ],
    }


def create_final_context(client, visit_id: str, *, with_report: bool = True):
    intake = client.post(
        f"/api/v1/visits/{visit_id}/clinical-intakes",
        json=intake_payload(),
    )
    assert intake.status_code == 201, intake.text
    finalized_intake = client.post(
        f"/api/v1/clinical-intakes/{intake.json()['id']}/finalize"
    )
    assert finalized_intake.status_code == 200, finalized_intake.text
    report = None
    if with_report:
        created_report = client.post(
            f"/api/v1/visits/{visit_id}/paraclinical-reports",
            json=report_payload(),
        )
        assert created_report.status_code == 201, created_report.text
        finalized_report = client.post(
            f"/api/v1/paraclinical-reports/{created_report.json()['id']}/finalize"
        )
        assert finalized_report.status_code == 200, finalized_report.text
        report = finalized_report.json()
    return finalized_intake.json(), report


def knowledge_payload(*, fact_key: str, title: str) -> dict:
    return {
        "fact_key": fact_key,
        "title": title,
        "statement": (
            "This synthetic source-linked evidence statement exists only for "
            "testing an independently reviewable evidence brief."
        ),
        "clinical_domain": "evidence brief testing",
        "therapy_type": None,
        "population": "Synthetic test population.",
        "indication": "Automated governance testing only.",
        "contraindications": ["Synthetic contraindication."],
        "evidence_grade": "ungraded",
        "valid_from": "2026-01-01",
        "sources": [
            {
                "source_type": "guideline",
                "title": f"{title} source",
                "citation": "Synthetic citation used by automated tests only.",
                "publisher": "4B-MOS Test Suite",
                "url": "https://example.test/evidence",
                "publication_date": "2025-01-01",
                "guideline_version": "1.0",
                "accessed_at": "2026-09-20",
            }
        ],
    }


def create_approved_fact(
    client,
    physician_headers,
    *,
    fact_key: str,
    title: str,
) -> dict:
    created = client.post(
        "/api/v1/knowledge/facts",
        json=knowledge_payload(fact_key=fact_key, title=title),
    )
    assert created.status_code == 201, created.text
    fact = created.json()
    assert client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/submit"
    ).status_code == 200
    reviewed = client.post(
        f"/api/v1/knowledge/facts/{fact['id']}/review",
        json={"decision": "approved", "comment": "Synthetic approval."},
        headers=physician_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()


def current_context_hash(client, visit_id: str) -> str:
    response = client.get(f"/api/v1/visits/{visit_id}/clinical-context")
    assert response.status_code == 200, response.text
    return clinical_context_digest(ClinicalContextRead.model_validate(response.json()))


def brief_payload(client, visit_id: str, facts: list[dict]) -> dict:
    return {
        "clinical_question": (
            "Which selected source statements should the physician independently "
            "review for this synthetic visit?"
        ),
        "expected_clinical_context_sha256": current_context_hash(client, visit_id),
        "facts": [
            {
                "fact_id": fact["id"],
                "expected_content_sha256": fact["content_sha256"],
            }
            for fact in facts
        ],
    }


def test_physician_creates_transparent_immutable_evidence_snapshot(
    client,
    visit,
    physician_headers,
):
    intake, report = create_final_context(client, visit["id"])
    z_fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="Z-EVIDENCE",
        title="Synthetic Z evidence",
    )
    a_fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="A-EVIDENCE",
        title="Synthetic A evidence",
    )
    response = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=brief_payload(client, visit["id"], [z_fact, a_fact]),
        headers=physician_headers,
    )
    assert response.status_code == 201, response.text
    brief = response.json()

    assert brief["intake_id"] == intake["id"]
    assert brief["report_ids"] == [report["id"]]
    assert brief["knowledge_fact_ids"] == [a_fact["id"], z_fact["id"]]
    assert [item["fact_key"] for item in brief["payload"]["facts"]] == [
        "A-EVIDENCE",
        "Z-EVIDENCE",
    ]
    assert brief["payload"]["ordering"] == "fact_key_then_version"
    assert brief["payload"]["selection_method"] == "clinician_selected"
    assert brief["payload"]["intended_use"] == "independent_evidence_review"
    assert brief["payload"]["context_manifest"]["intake"]["id"] == intake["id"]
    assert brief["payload"]["context_manifest"]["reports"][0]["id"] == report["id"]
    assert brief["payload"]["facts"][0]["sources"][0]["citation"]
    assert evidence_digest(brief["payload"]) == brief["sha256"]
    assert brief["is_recommendation"] is False
    assert brief["ranks_treatments"] is False
    assert brief["provides_risk_score"] is False
    assert brief["is_clinical_clearance"] is False
    assert brief["is_time_critical"] is False
    assert brief["requires_independent_review"] is True

    fetched = client.get(
        f"/api/v1/evidence-briefs/{brief['id']}",
        headers=physician_headers,
    )
    listed = client.get(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        headers=physician_headers,
    )
    assert fetched.status_code == 200
    assert fetched.json() == brief
    assert listed.json() == [brief]


def test_brief_requires_final_context_and_exact_optimistic_hashes(
    client,
    visit,
    physician_headers,
):
    fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="HASH-EVIDENCE",
        title="Synthetic hash evidence",
    )
    empty_hash = current_context_hash(client, visit["id"])
    no_intake = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json={
            "clinical_question": "Synthetic question without a final intake?",
            "expected_clinical_context_sha256": empty_hash,
            "facts": [
                {
                    "fact_id": fact["id"],
                    "expected_content_sha256": fact["content_sha256"],
                }
            ],
        },
        headers=physician_headers,
    )
    assert no_intake.status_code == 409
    assert "final clinical intake" in no_intake.json()["detail"]

    create_final_context(client, visit["id"], with_report=False)
    payload = brief_payload(client, visit["id"], [fact])
    payload["expected_clinical_context_sha256"] = "0" * 64
    stale_context = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=payload,
        headers=physician_headers,
    )
    assert stale_context.status_code == 409
    assert "clinical context changed" in stale_context.json()["detail"]

    payload = brief_payload(client, visit["id"], [fact])
    payload["facts"][0]["expected_content_sha256"] = "0" * 64
    stale_fact = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=payload,
        headers=physician_headers,
    )
    assert stale_fact.status_code == 409
    assert "changed" in stale_fact.json()["detail"]


def test_only_current_approved_facts_can_enter_new_brief(
    client,
    visit,
    physician_headers,
):
    create_final_context(client, visit["id"], with_report=False)
    draft = client.post(
        "/api/v1/knowledge/facts",
        json=knowledge_payload(
            fact_key="DRAFT-EVIDENCE",
            title="Synthetic draft evidence",
        ),
    ).json()
    response = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=brief_payload(client, visit["id"], [draft]),
        headers=physician_headers,
    )
    assert response.status_code == 409
    assert "not currently approved" in response.json()["detail"]


def test_role_boundaries_and_historical_read_after_retirement(
    client,
    visit,
    physician_headers,
    nurse_headers,
):
    create_final_context(client, visit["id"], with_report=False)
    fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="ROLE-EVIDENCE",
        title="Synthetic role evidence",
    )
    payload = brief_payload(client, visit["id"], [fact])
    assert client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=payload,
    ).status_code == 403
    assert client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=payload,
        headers=nurse_headers,
    ).status_code == 403
    created = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=payload,
        headers=physician_headers,
    )
    assert created.status_code == 201, created.text
    brief = created.json()

    retired = client.post(f"/api/v1/knowledge/facts/{fact['id']}/retire")
    assert retired.status_code == 200, retired.text
    assert client.get(
        f"/api/v1/evidence-briefs/{brief['id']}"
    ).status_code == 200
    assert client.get(
        f"/api/v1/evidence-briefs/{brief['id']}",
        headers=nurse_headers,
    ).status_code == 200
    viewer = create_role_headers(
        client,
        username="evidence_viewer",
        role="viewer",
    )
    assert client.get(
        f"/api/v1/evidence-briefs/{brief['id']}",
        headers=viewer,
    ).status_code == 403


def test_brief_integrity_and_orm_immutability(
    client,
    visit,
    physician_headers,
    db_session,
):
    create_final_context(client, visit["id"], with_report=False)
    fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="INTEGRITY-EVIDENCE",
        title="Synthetic integrity evidence",
    )
    created = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=brief_payload(client, visit["id"], [fact]),
        headers=physician_headers,
    ).json()

    record = db_session.get(ClinicalEvidenceBrief, created["id"])
    record.output_type = "evidence_summary"
    with pytest.raises(ValueError, match="cannot be updated"):
        db_session.commit()
    db_session.rollback()

    tampered = deepcopy(record.payload)
    tampered["clinical_question"] = "Tampered clinical question"
    db_session.execute(
        update(ClinicalEvidenceBrief)
        .where(ClinicalEvidenceBrief.id == created["id"])
        .values(payload=tampered)
    )
    db_session.commit()
    response = client.get(
        f"/api/v1/evidence-briefs/{created['id']}",
        headers=physician_headers,
    )
    assert response.status_code == 409
    assert "integrity check" in response.json()["detail"]


def test_brief_write_and_audit_are_atomic_and_audit_is_minimized(
    client,
    visit,
    physician_headers,
    db_session,
    monkeypatch,
):
    create_final_context(client, visit["id"], with_report=False)
    fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="AUDIT-EVIDENCE",
        title="Synthetic audit evidence",
    )
    payload = brief_payload(client, visit["id"], [fact])
    created = client.post(
        f"/api/v1/visits/{visit['id']}/evidence-briefs",
        json=payload,
        headers=physician_headers,
    )
    assert created.status_code == 201, created.text
    brief = created.json()
    audit = client.get(
        f"/api/v1/evidence-briefs/{brief['id']}/audit-logs",
        headers=physician_headers,
    )
    assert audit.status_code == 200
    assert len(audit.json()) == 1
    assert payload["clinical_question"] not in audit.text
    assert fact["statement"] not in audit.text
    assert audit.json()[0]["event_data"]["is_recommendation"] is False

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit outage")

    monkeypatch.setattr(AuditLogRepository, "create", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        client.post(
            f"/api/v1/visits/{visit['id']}/evidence-briefs",
            json=payload,
            headers=physician_headers,
        )
    assert db_session.query(ClinicalEvidenceBrief).count() == 1


def test_empty_or_duplicate_selection_is_rejected_and_unknowns_are_404(
    client,
    visit,
    physician_headers,
):
    create_final_context(client, visit["id"], with_report=False)
    fact = create_approved_fact(
        client,
        physician_headers,
        fact_key="VALIDATION-EVIDENCE",
        title="Synthetic validation evidence",
    )
    base = brief_payload(client, visit["id"], [fact])
    empty = deepcopy(base)
    empty["facts"] = []
    duplicate = deepcopy(base)
    duplicate["facts"] = [base["facts"][0], base["facts"][0]]
    url = f"/api/v1/visits/{visit['id']}/evidence-briefs"
    assert client.post(url, json=empty, headers=physician_headers).status_code == 422
    assert client.post(
        url,
        json=duplicate,
        headers=physician_headers,
    ).status_code == 422
    assert client.get(
        "/api/v1/evidence-briefs/missing",
        headers=physician_headers,
    ).status_code == 404
    assert client.get(
        "/api/v1/visits/missing/evidence-briefs",
        headers=physician_headers,
    ).status_code == 404
