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
            "chief_complaint": "Knee pain",
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
            "treatment_type": "ACS",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201
    return response.json()


def test_create_treatment_session(client):
    treatment = create_treatment(client)

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
            "body_region": "Knee",
            "dose_or_volume": "4 mL",
            "execution_parameters": {
                "documentation": "session 1",
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["treatment_id"] == treatment["id"]
    assert data["session_number"] == 1
    assert data["status"] == "planned"
    assert data["body_region"] == "Knee"
    assert data["dose_or_volume"] == "4 mL"


def test_list_treatment_sessions_in_session_order(client):
    treatment = create_treatment(client)

    second = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 2,
        },
    )

    first = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert second.status_code == 201
    assert first.status_code == 201

    response = client.get(
        f"/api/v1/treatments/{treatment['id']}/sessions"
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 2
    assert data[0]["session_number"] == 1
    assert data[1]["session_number"] == 2


def test_get_treatment_session(client):
    treatment = create_treatment(client)

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert create_response.status_code == 201

    session_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/treatment-sessions/{session_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == session_id
    assert data["treatment_id"] == treatment["id"]
    assert data["session_number"] == 1


def test_update_treatment_session(client):
    treatment = create_treatment(client)

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert create_response.status_code == 201

    session_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/treatment-sessions/{session_id}",
        json={
            "status": "completed",
            "dose_or_volume": "5 mL",
            "execution_parameters": {
                "actual_volume": "5 mL",
                "completed": True,
            },
            "outcome_summary": "Procedure completed successfully",
            "adverse_events": "None reported",
            "notes": "Session completed",
            "started_at": "2026-08-31T08:00:00Z",
            "completed_at": "2026-08-31T08:30:00Z",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "completed"
    assert data["dose_or_volume"] == "5 mL"

    assert (
        data["execution_parameters"]["actual_volume"]
        == "5 mL"
    )

    assert (
        data["outcome_summary"]
        == "Procedure completed successfully"
    )

    assert data["adverse_events"] == "None reported"
    assert data["started_at"] is not None
    assert data["completed_at"] is not None


def test_duplicate_session_number_returns_409(client):
    treatment = create_treatment(client)

    first = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    second = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_create_session_for_missing_treatment_returns_404(client):
    response = client.post(
        "/api/v1/treatments/not-real/sessions",
        json={
            "session_number": 1,
        },
    )

    assert response.status_code == 404


def test_invalid_session_status_returns_422(client):
    treatment = create_treatment(client)

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
            "status": "banana",
        },
    )

    assert response.status_code == 422