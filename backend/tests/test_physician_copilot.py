import pytest

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
def visit(client):
    patient = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "COPILOT-001",
            "first_name": "Copilot",
            "last_name": "Fixture",
            "date_of_birth": "1980-01-02",
        },
    )
    assert patient.status_code == 201, patient.text
    response = client.post(
        f"/api/v1/patients/{patient.json()['id']}/visits",
        json={
            "chief_complaint": "Synthetic physician copilot visit",
            "body_region": "knee",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_reads_traceable_empty_physician_snapshot(client, visit):
    response = client.get(
        f"/api/v1/visits/{visit['id']}/physician-copilot"
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["visit_id"] == visit["id"]
    assert body["clinical_context"]["visit_id"] == visit["id"]
    assert body["clinical_context"]["intake"] is None
    assert body["clinical_context"]["reports"] == []
    assert (
        body["manifest"]["clinical_context_sha256"]
        == body["clinical_context"]["clinical_context_sha256"]
    )
    assert (
        body["safety_inbox"]["current_clinical_context_sha256"]
        == body["clinical_context"]["clinical_context_sha256"]
    )
    assert body["safety_inbox"]["evaluation"] is None
    assert body["safety_inbox"]["findings"] == []
    assert body["open_escalations"] == []
    assert body["evidence_briefs"] == []
    assert body["current_context_evidence_briefs"] == []
    assert body["manifest"]["safety_evaluation_result_sha256"] is None
    assert body["manifest"]["open_escalation_review_sha256s"] == []
    assert body["manifest"]["evidence_brief_sha256s"] == []
    assert body["open_escalation_scope"] == "latest_safety_evaluation_for_visit"
    assert body["is_diagnosis"] is False
    assert body["is_recommendation"] is False
    assert body["ranks_treatments"] is False
    assert body["provides_risk_score"] is False
    assert body["is_clinical_clearance"] is False
    assert body["requires_independent_review"] is True

    assert body["snapshot_sha256"] == evidence_digest(
        {
            "schema_version": 1,
            "visit_id": visit["id"],
            "manifest": body["manifest"],
        }
    )


def test_physician_can_read_but_non_physician_clinical_roles_cannot(
    client,
    visit,
):
    physician = create_role_headers(
        client,
        username="copilot_physician",
        role="physician",
    )
    nurse = create_role_headers(
        client,
        username="copilot_nurse",
        role="nurse",
    )
    viewer = create_role_headers(
        client,
        username="copilot_viewer",
        role="viewer",
    )

    assert client.get(
        f"/api/v1/visits/{visit['id']}/physician-copilot",
        headers=physician,
    ).status_code == 200
    assert client.get(
        f"/api/v1/visits/{visit['id']}/physician-copilot",
        headers=nurse,
    ).status_code == 403
    assert client.get(
        f"/api/v1/visits/{visit['id']}/physician-copilot",
        headers=viewer,
    ).status_code == 403


def test_unknown_visit_is_not_found(client):
    response = client.get("/api/v1/visits/missing/physician-copilot")
    assert response.status_code == 404
