def create_patient(client) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "RULE-PAT-001",
            "first_name": "Rule",
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


def create_protocol(
    client,
    treatment_type="PRP",
) -> dict:
    response = client.post(
        "/api/v1/protocols",
        json={
            "code": f"{treatment_type}-RULE-001",
            "name": f"{treatment_type} Protocol",
            "treatment_type": treatment_type,
            "version": "1.0",
        },
    )

    assert response.status_code == 201

    return response.json()


def test_matching_protocol_can_be_attached(client):
    visit = create_visit(client)
    protocol = create_protocol(
        client,
        treatment_type="PRP",
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": protocol["id"],
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["protocol_template_id"] == protocol["id"]
    assert data["protocol_name"] == protocol["name"]
    assert data["protocol_version"] == "1.0"


def test_mismatched_protocol_returns_409(client):
    visit = create_visit(client)
    protocol = create_protocol(
        client,
        treatment_type="ACS",
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": protocol["id"],
        },
    )

    assert response.status_code == 409


def test_missing_protocol_returns_404(client):
    visit = create_visit(client)

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": "not-real",
        },
    )

    assert response.status_code == 404


def test_inactive_protocol_returns_409(client):
    visit = create_visit(client)
    protocol = create_protocol(
        client,
        treatment_type="PRGF",
    )

    deactivate_response = client.delete(
        f"/api/v1/protocols/{protocol['id']}"
    )

    assert deactivate_response.status_code == 200

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRGF",
            "protocol_template_id": protocol["id"],
        },
    )

    assert response.status_code == 409