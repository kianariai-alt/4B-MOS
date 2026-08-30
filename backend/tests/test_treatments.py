def create_patient(client) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "TREATMENT-PAT-001",
            "first_name": "Treatment",
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


def test_create_prp_treatment(client):
    visit = create_visit(client)

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "session_number": 1,
            "body_region": "Knee",
            "protocol_name": "PRP Knee Protocol",
            "dose_or_volume": "5 mL",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["treatment_type"] == "PRP"
    assert data["status"] == "planned"
    assert data["session_number"] == 1
    assert data["visit_id"] == visit["id"]


def test_create_all_supported_treatment_types(client):
    visit = create_visit(client)

    treatment_types = [
        "PRP",
        "PRGF",
        "ACS",
        "PL",
        "SVF",
        "EXOSOME",
    ]

    for index, treatment_type in enumerate(
        treatment_types,
        start=1,
    ):
        response = client.post(
            f"/api/v1/visits/{visit['id']}/treatments",
            json={
                "treatment_type": treatment_type,
                "session_number": index,
            },
        )

        assert response.status_code == 201
        assert response.json()["treatment_type"] == treatment_type


def test_invalid_treatment_type_returns_422(client):
    visit = create_visit(client)

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "MAGIC",
        },
    )

    assert response.status_code == 422


def test_create_treatment_for_missing_visit_returns_404(client):
    response = client.post(
        "/api/v1/visits/not-real/treatments",
        json={
            "treatment_type": "PRP",
        },
    )

    assert response.status_code == 404


def test_list_visit_treatments(client):
    visit = create_visit(client)

    client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "session_number": 1,
        },
    )

    client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "ACS",
            "session_number": 2,
        },
    )

    response = client.get(
        f"/api/v1/visits/{visit['id']}/treatments"
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_treatment(client):
    visit = create_visit(client)

    create_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRGF",
        },
    )

    treatment_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/treatments/{treatment_id}"
    )

    assert response.status_code == 200
    assert response.json()["treatment_type"] == "PRGF"


def test_update_treatment(client):
    visit = create_visit(client)

    create_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "ACS",
        },
    )

    treatment_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/treatments/{treatment_id}",
        json={
            "status": "completed",
            "dose_or_volume": "4 mL",
            "notes": "Procedure completed",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["dose_or_volume"] == "4 mL"


def test_invalid_treatment_status_returns_422(client):
    visit = create_visit(client)

    create_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "SVF",
        },
    )

    treatment_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/treatments/{treatment_id}",
        json={
            "status": "banana",
        },
    )

    assert response.status_code == 422


def test_missing_treatment_returns_404(client):
    response = client.get(
        "/api/v1/treatments/not-real"
    )

    assert response.status_code == 404