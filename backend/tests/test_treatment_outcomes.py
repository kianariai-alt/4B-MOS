from copy import deepcopy

import pytest
from sqlalchemy import update

from backend.app.models.treatment_outcome import TreatmentOutcome
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
        username="outcome_physician",
        role="physician",
    )


@pytest.fixture
def nurse_headers(client):
    return create_role_headers(
        client,
        username="outcome_nurse",
        role="nurse",
    )


def create_final_intake(client, visit_id: str, headers: dict) -> dict:
    created = client.post(
        f"/api/v1/visits/{visit_id}/clinical-intakes",
        headers=headers,
        json={
            "chief_complaint": "Synthetic knee pain",
            "history_present_illness": "Synthetic history for outcome testing.",
            "body_region": "Knee",
            "laterality": "right",
            "pain_score": 7,
            "functional_limitations": ["Stairs"],
            "relevant_history": [],
            "current_medications": [],
            "allergies": [],
            "exam_findings": "Synthetic examination.",
            "red_flags": [],
            "clinical_impression": "Synthetic clinical impression.",
            "care_goal": "Synthetic mobility goal.",
        },
    )
    assert created.status_code == 201, created.text
    finalized = client.post(
        f"/api/v1/clinical-intakes/{created.json()['id']}/finalize",
        headers=headers,
    )
    assert finalized.status_code == 200, finalized.text
    return finalized.json()


def current_context_hash(client, visit_id: str, headers: dict) -> str:
    response = client.get(
        f"/api/v1/visits/{visit_id}/clinical-context",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["clinical_context_sha256"]


def create_completed_treatment(client, physician_headers) -> tuple[dict, dict]:
    patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "OUTCOME-001",
            "first_name": "Outcome",
            "last_name": "Fixture",
            "date_of_birth": "1980-01-02",
        },
    )
    assert patient.status_code == 201, patient.text
    visit = client.post(
        f"/api/v1/patients/{patient.json()['id']}/visits",
        json={
            "chief_complaint": "Synthetic knee pain",
            "body_region": "Knee",
        },
    )
    assert visit.status_code == 201, visit.text
    visit = visit.json()
    create_final_intake(client, visit["id"], physician_headers)

    protocol = client.post(
        "/api/v1/protocols",
        headers=physician_headers,
        json={
            "code": "OUTCOME-ACS-KNEE",
            "name": "Synthetic ACS Outcome Protocol",
            "treatment_type": "ACS",
            "version": "1.0",
            "description": "Synthetic protocol for outcome registry tests.",
        },
    )
    assert protocol.status_code == 201, protocol.text

    treatment = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician_headers,
        json={
            "treatment_type": "ACS",
            "protocol_template_id": protocol.json()["id"],
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert treatment.status_code == 201, treatment.text
    treatment = treatment.json()

    session = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=physician_headers,
        json={
            "session_number": 1,
            "body_region": "Knee",
            "dose_or_volume": "3 ml",
        },
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]
    for state in ("checked_in", "ready", "in_treatment", "completed"):
        response = client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=physician_headers,
            json={"operational_status": state},
        )
        assert response.status_code == 200, response.text

    finalization = client.get(
        f"/api/v1/treatment-sessions/{session_id}/finalization",
        headers=physician_headers,
    )
    assert finalization.status_code == 200, finalization.text
    return visit, treatment


def outcome_payload(client, visit_id: str, headers: dict) -> dict:
    return {
        "expected_clinical_context_sha256": current_context_hash(
            client,
            visit_id,
            headers,
        ),
        "follow_up_day": 42,
        "outcome_status": "improved",
        "patient_rating": 5,
        "physician_rating": 4,
        "pain_score": 3,
        "function_score": 78,
        "outcome_measures": [
            {
                "measure_key": "KOOS-PS",
                "label": "Synthetic KOOS physical function",
                "instrument": "KOOS-PS",
                "value": "78",
                "scale_min": "0",
                "scale_max": "100",
                "higher_is_better": True,
            }
        ],
        "adverse_events": [],
        "notes": "Synthetic six-week follow-up.",
    }


def test_physician_records_immutable_traceable_outcome(
    client,
    physician_headers,
):
    visit, treatment = create_completed_treatment(
        client,
        physician_headers,
    )
    payload = outcome_payload(client, visit["id"], physician_headers)
    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    outcome = response.json()

    assert outcome["treatment_id"] == treatment["id"]
    assert outcome["visit_id"] == visit["id"]
    assert outcome["treatment_type"] == "ACS"
    assert outcome["protocol_code"] == "OUTCOME-ACS-KNEE"
    assert outcome["protocol_version"] == "1.0"
    assert outcome["follow_up_day"] == 42
    assert outcome["outcome_status"] == "improved"
    assert outcome["patient_rating"] == 5
    assert outcome["physician_rating"] == 4
    assert outcome["pain_score"] == 3
    assert outcome["function_score"] == 78
    assert len(outcome["finalization_sha256s"]) == 1
    assert outcome["payload"]["patient_rating_source"] == "patient_reported"
    assert outcome["payload"]["treatment_snapshot"]["id"] == treatment["id"]
    assert (
        evidence_digest(outcome["payload"]["treatment_snapshot"])
        == outcome["treatment_snapshot_sha256"]
    )
    assert evidence_digest(outcome["payload"]) == outcome["sha256"]
    assert outcome["is_causal_evidence"] is False
    assert outcome["is_treatment_recommendation"] is False
    assert outcome["requires_bias_review"] is True

    listed = client.get(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
    )
    fetched = client.get(
        f"/api/v1/treatment-outcomes/{outcome['id']}",
        headers=physician_headers,
    )
    assert listed.status_code == 200
    assert listed.json() == [outcome]
    assert fetched.status_code == 200
    assert fetched.json() == outcome

    audit = client.get(
        f"/api/v1/treatment-outcomes/{outcome['id']}/audit-logs",
        headers=physician_headers,
    )
    assert audit.status_code == 200
    assert len(audit.json()) == 1
    assert audit.json()[0]["event_type"] == "treatment_outcome_recorded"
    assert audit.json()[0]["event_data"]["is_causal_evidence"] is False


def test_outcome_requires_completed_session_finalization(
    client,
    physician_headers,
):
    patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "OUTCOME-NOFINAL",
            "first_name": "No",
            "last_name": "Finalization",
        },
    ).json()
    visit = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={"body_region": "Knee"},
    ).json()
    create_final_intake(client, visit["id"], physician_headers)
    treatment = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician_headers,
        json={"treatment_type": "PL", "body_region": "Knee"},
    ).json()

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
        json=outcome_payload(client, visit["id"], physician_headers),
    )
    assert response.status_code == 409
    assert "finalization" in response.json()["detail"]


def test_outcome_rejects_stale_context_and_empty_observation(
    client,
    physician_headers,
):
    visit, treatment = create_completed_treatment(
        client,
        physician_headers,
    )
    payload = outcome_payload(client, visit["id"], physician_headers)
    payload["expected_clinical_context_sha256"] = "0" * 64
    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
        json=payload,
    )
    assert response.status_code == 409
    assert "clinical context changed" in response.json()["detail"]

    empty = {
        "expected_clinical_context_sha256": current_context_hash(
            client,
            visit["id"],
            physician_headers,
        ),
        "follow_up_day": 42,
        "outcome_status": "unknown",
    }
    assert client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
        json=empty,
    ).status_code == 422


def test_outcome_role_boundaries(
    client,
    physician_headers,
    nurse_headers,
):
    visit, treatment = create_completed_treatment(
        client,
        physician_headers,
    )
    payload = outcome_payload(client, visit["id"], physician_headers)

    assert client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=nurse_headers,
        json=payload,
    ).status_code == 403

    created = client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    outcome_id = created.json()["id"]

    assert client.get(
        f"/api/v1/treatment-outcomes/{outcome_id}",
        headers=nurse_headers,
    ).status_code == 200

    viewer = create_role_headers(
        client,
        username="outcome_viewer",
        role="viewer",
    )
    assert client.get(
        f"/api/v1/treatment-outcomes/{outcome_id}",
        headers=viewer,
    ).status_code == 403


def test_outcome_orm_immutability_and_checksum_detection(
    client,
    physician_headers,
    db_session,
):
    visit, treatment = create_completed_treatment(
        client,
        physician_headers,
    )
    created = client.post(
        f"/api/v1/treatments/{treatment['id']}/outcomes",
        headers=physician_headers,
        json=outcome_payload(client, visit["id"], physician_headers),
    )
    assert created.status_code == 201, created.text
    outcome = created.json()

    record = db_session.get(TreatmentOutcome, outcome["id"])
    record.patient_rating = 1
    with pytest.raises(ValueError, match="cannot be updated"):
        db_session.commit()
    db_session.rollback()

    tampered = deepcopy(record.payload)
    tampered["outcome_status"] = "worsened"
    db_session.execute(
        update(TreatmentOutcome)
        .where(TreatmentOutcome.id == outcome["id"])
        .values(payload=tampered)
    )
    db_session.commit()
    response = client.get(
        f"/api/v1/treatment-outcomes/{outcome['id']}",
        headers=physician_headers,
    )
    assert response.status_code == 409
    assert "integrity check" in response.json()["detail"]
