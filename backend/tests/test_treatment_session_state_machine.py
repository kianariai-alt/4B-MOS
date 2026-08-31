import pytest


@pytest.fixture(autouse=True)
def authenticate_session_tests(
    client,
    admin_headers,
):
    create_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "statedoctor",
            "display_name": "State Doctor",
            "password": "StrongPass123",
            "role": "physician",
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "statedoctor",
            "password": "StrongPass123",
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    client.headers.update(
        {
            "Authorization": f"Bearer {token}",
        }
    )


def create_patient(client) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "STATE-PAT-001",
            "first_name": "State",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_visit(client) -> dict:
    patient = create_patient(client)

    response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_treatment(client) -> dict:
    visit = create_visit(client)

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_treatment_with_session(
    client,
) -> dict:
    treatment = create_treatment(
        client
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert response.status_code == 201

    return response.json()


def test_session_creation_writes_audit_log(
    client,
):
    session = create_treatment_with_session(
        client
    )

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/audit-logs"
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 1

    assert (
        logs[0]["event_type"]
        == "session_created"
    )

    assert logs[0]["from_state"] is None

    assert (
        logs[0]["to_state"]
        == "planned"
    )

    assert (
        logs[0]["actor_username"]
        == "statedoctor"
    )


def test_planned_to_in_progress_is_allowed(
    client,
):
    session = create_treatment_with_session(
        client
    )

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "in_progress",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "in_progress"

    assert data["started_at"] is not None


def test_in_progress_to_completed_is_allowed(
    client,
):
    session = create_treatment_with_session(
        client
    )

    start_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "in_progress",
        },
    )

    assert start_response.status_code == 200

    complete_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "completed",
        },
    )

    assert complete_response.status_code == 200

    data = complete_response.json()

    assert data["status"] == "completed"

    assert (
        data["completed_at"]
        is not None
    )


def test_planned_to_cancelled_is_allowed(
    client,
):
    session = create_treatment_with_session(
        client
    )

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "cancelled",
        },
    )

    assert response.status_code == 200

    assert (
        response.json()["status"]
        == "cancelled"
    )


def test_planned_to_completed_is_rejected(
    client,
):
    session = create_treatment_with_session(
        client
    )

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "completed",
        },
    )

    assert response.status_code == 409


def test_completed_to_in_progress_is_rejected(
    client,
):
    session = create_treatment_with_session(
        client
    )

    start_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "in_progress",
        },
    )

    assert start_response.status_code == 200

    complete_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "completed",
        },
    )

    assert complete_response.status_code == 200

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "in_progress",
        },
    )

    assert response.status_code == 409


def test_cancelled_to_completed_is_rejected(
    client,
):
    session = create_treatment_with_session(
        client
    )

    cancel_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "cancelled",
        },
    )

    assert cancel_response.status_code == 200

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "completed",
        },
    )

    assert response.status_code == 409


def test_state_transitions_are_recorded_in_audit_log(
    client,
):
    session = create_treatment_with_session(
        client
    )

    start_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "in_progress",
        },
    )

    assert start_response.status_code == 200

    complete_response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "completed",
        },
    )

    assert complete_response.status_code == 200

    audit_response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/audit-logs"
    )

    assert audit_response.status_code == 200

    logs = audit_response.json()

    assert len(logs) == 3

    assert (
        logs[0]["event_type"]
        == "session_created"
    )

    assert (
        logs[1]["event_type"]
        == "state_transition"
    )

    assert (
        logs[1]["from_state"]
        == "planned"
    )

    assert (
        logs[1]["to_state"]
        == "in_progress"
    )

    assert (
        logs[2]["event_type"]
        == "state_transition"
    )

    assert (
        logs[2]["from_state"]
        == "in_progress"
    )

    assert (
        logs[2]["to_state"]
        == "completed"
    )

    assert (
        logs[1]["actor_username"]
        == "statedoctor"
    )

    assert (
        logs[2]["actor_username"]
        == "statedoctor"
    )