def create_treatment(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "CREATE-GUARD-001",
            "first_name": "Create",
            "last_name": "Guard",
        },
    )

    assert patient_response.status_code == 201
    patient = patient_response.json()

    visit_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        headers=admin_headers,
        json={
            "body_region": "Knee",
        },
    )

    assert visit_response.status_code == 201
    visit = visit_response.json()

    treatment_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert treatment_response.status_code == 201

    return treatment_response.json()


def test_session_is_created_in_initial_states(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=admin_headers,
        json={
            "session_number": 1,
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["status"] == "planned"
    assert data["operational_status"] == "scheduled"

    assert data["started_at"] is None
    assert data["completed_at"] is None
    assert data["discharged_at"] is None


def test_status_cannot_be_set_on_creation(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=admin_headers,
        json={
            "session_number": 1,
            "status": "completed",
        },
    )

    assert response.status_code == 422


def test_operational_status_cannot_be_set_on_creation(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=admin_headers,
        json={
            "session_number": 1,
            "operational_status": "completed",
        },
    )

    assert response.status_code == 422
