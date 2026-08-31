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
            "username": "sessiondoctor",
            "display_name": "Session Doctor",
            "password": "StrongPass123",
            "role": "physician",
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "sessiondoctor",
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
            "patient_code": "SESSION-PAT-001",
            "first_name": "Session",
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


def test_create_treatment_session(
    client,
):
    treatment = create_treatment(
        client
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
            "body_region": "Knee",
            "dose_or_volume": "4 ml",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert (
        data["treatment_id"]
        == treatment["id"]
    )

    assert data["session_number"] == 1
    assert data["status"] == "planned"
    assert data["body_region"] == "Knee"


def test_list_treatment_sessions_in_session_order(
    client,
):
    treatment = create_treatment(
        client
    )

    second = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 2,
        },
    )

    assert second.status_code == 201

    first = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert first.status_code == 201

    response = client.get(
        f"/api/v1/treatments/{treatment['id']}/sessions"
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 2

    assert [
        item["session_number"]
        for item in data
    ] == [1, 2]


def test_get_treatment_session(
    client,
):
    treatment = create_treatment(
        client
    )

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert create_response.status_code == 201

    session = create_response.json()

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == session["id"]


def test_update_treatment_session(
    client,
):
    treatment = create_treatment(
        client
    )

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert create_response.status_code == 201

    session = create_response.json()

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        json={
            "status": "in_progress",
            "dose_or_volume": "5 ml",
            "notes": "Session started",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "in_progress"

    assert (
        data["dose_or_volume"]
        == "5 ml"
    )

    assert data["started_at"] is not None


def test_duplicate_session_number_returns_409(
    client,
):
    treatment = create_treatment(
        client
    )

    first = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert first.status_code == 201

    second = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert second.status_code == 409


def test_create_session_for_missing_treatment_returns_404(
    client,
):
    response = client.post(
        "/api/v1/treatments/not-real/sessions",
        json={
            "session_number": 1,
        },
    )

    assert response.status_code == 404


def test_invalid_session_status_returns_422(
    client,
):
    treatment = create_treatment(
        client
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
            "status": "finished",
        },
    )

    assert response.status_code == 422