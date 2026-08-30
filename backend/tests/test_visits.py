def create_patient(
    client,
    patient_code: str = "VISIT-PAT-001",
) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": patient_code,
            "first_name": "Visit",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    return response.json()


def test_create_visit(client):
    patient = create_patient(client)

    response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "chief_complaint": "Knee pain",
            "body_region": "Knee",
            "diagnosis": "Osteoarthritis",
            "notes": "Initial evaluation",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["patient_id"] == patient["id"]
    assert data["status"] == "open"
    assert data["body_region"] == "Knee"


def test_create_visit_for_missing_patient_returns_404(client):
    response = client.post(
        "/api/v1/patients/not-real/visits",
        json={
            "chief_complaint": "Pain",
        },
    )

    assert response.status_code == 404


def test_list_patient_visits(client):
    patient = create_patient(client)

    first_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "chief_complaint": "First visit",
        },
    )

    second_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "chief_complaint": "Second visit",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    response = client.get(
        f"/api/v1/patients/{patient['id']}/visits"
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_visit(client):
    patient = create_patient(client)

    create_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "body_region": "Shoulder",
        },
    )

    assert create_response.status_code == 201

    visit_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/visits/{visit_id}"
    )

    assert response.status_code == 200
    assert response.json()["body_region"] == "Shoulder"


def test_update_visit(client):
    patient = create_patient(client)

    create_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "body_region": "Knee",
        },
    )

    assert create_response.status_code == 201

    visit_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/visits/{visit_id}",
        json={
            "status": "completed",
            "diagnosis": "Knee osteoarthritis",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["diagnosis"] == "Knee osteoarthritis"


def test_missing_visit_returns_404(client):
    response = client.get(
        "/api/v1/visits/not-a-real-visit"
    )

    assert response.status_code == 404


def test_invalid_visit_status_returns_422(client):
    patient = create_patient(client)

    create_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={},
    )

    assert create_response.status_code == 201

    visit_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/visits/{visit_id}",
        json={
            "status": "banana",
        },
    )

    assert response.status_code == 422