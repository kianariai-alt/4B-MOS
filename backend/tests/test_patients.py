def test_create_patient(client):
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0001",
            "first_name": "Test",
            "last_name": "Patient",
            "date_of_birth": "1990-01-01",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["patient_code"] == "PAT-0001"
    assert data["first_name"] == "Test"
    assert data["last_name"] == "Patient"
    assert data["is_active"] is True
    assert "id" in data


def test_duplicate_patient_code_returns_conflict(client):
    payload = {
        "patient_code": "PAT-0002",
        "first_name": "Test",
        "last_name": "Patient",
    }

    first_response = client.post(
        "/api/v1/patients",
        json=payload,
    )

    second_response = client.post(
        "/api/v1/patients",
        json=payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_get_patient(client):
    create_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0003",
            "first_name": "Kian",
            "last_name": "Test",
        },
    )

    assert create_response.status_code == 201

    patient_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/patients/{patient_id}"
    )

    assert response.status_code == 200
    assert response.json()["patient_code"] == "PAT-0003"


def test_list_patients(client):
    first_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0004",
            "first_name": "First",
            "last_name": "Patient",
        },
    )

    second_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0005",
            "first_name": "Second",
            "last_name": "Patient",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    response = client.get(
        "/api/v1/patients"
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_update_patient(client):
    create_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0006",
            "first_name": "Before",
            "last_name": "Update",
        },
    )

    assert create_response.status_code == 201

    patient_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={
            "first_name": "After",
        },
    )

    assert response.status_code == 200
    assert response.json()["first_name"] == "After"


def test_deactivate_patient(client):
    create_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0007",
            "first_name": "Active",
            "last_name": "Patient",
        },
    )

    assert create_response.status_code == 201

    patient_id = create_response.json()["id"]

    response = client.delete(
        f"/api/v1/patients/{patient_id}"
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_missing_patient_returns_404(client):
    response = client.get(
        "/api/v1/patients/not-a-real-id"
    )

    assert response.status_code == 404