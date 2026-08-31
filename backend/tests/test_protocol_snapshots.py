import pytest


pytestmark = pytest.mark.usefixtures(
    "authenticated_admin"
)
def create_patient(client) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "SNAPSHOT-PAT-001",
            "first_name": "Snapshot",
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


def create_protocol(client) -> dict:
    response = client.post(
        "/api/v1/protocols",
        json={
            "code": "PRP-SNAPSHOT-001",
            "name": "PRP Snapshot Protocol",
            "treatment_type": "PRP",
            "version": "1.0",
            "description": "Snapshot test protocol",
            "preparation_parameters": {
                "preparation_mode": "configured",
                "step_count": 3,
            },
            "administration_parameters": {
                "route": "configured",
            },
            "monitoring_parameters": {
                "follow_up": "configured",
            },
        },
    )

    assert response.status_code == 201
    return response.json()


def test_protocol_snapshot_is_created(client):
    visit = create_visit(client)
    protocol = create_protocol(client)

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": protocol["id"],
            "execution_parameters": {
                "actual_volume": "5 mL",
                "operator": "test",
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["protocol_snapshot"] is not None

    snapshot = data["protocol_snapshot"]

    assert snapshot["code"] == "PRP-SNAPSHOT-001"
    assert snapshot["version"] == "1.0"
    assert snapshot["treatment_type"] == "PRP"

    assert data["execution_parameters"]["actual_volume"] == "5 mL"


def test_snapshot_survives_protocol_deactivation(client):
    visit = create_visit(client)
    protocol = create_protocol(client)

    treatment_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": protocol["id"],
        },
    )

    assert treatment_response.status_code == 201

    treatment_id = treatment_response.json()["id"]

    deactivate_response = client.delete(
        f"/api/v1/protocols/{protocol['id']}"
    )

    assert deactivate_response.status_code == 200

    response = client.get(
        f"/api/v1/treatments/{treatment_id}"
    )

    assert response.status_code == 200

    snapshot = response.json()["protocol_snapshot"]

    assert snapshot["code"] == "PRP-SNAPSHOT-001"
    assert snapshot["version"] == "1.0"


def test_same_protocol_can_have_different_execution_data(client):
    visit = create_visit(client)
    protocol = create_protocol(client)

    first = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": protocol["id"],
            "session_number": 1,
            "execution_parameters": {
                "actual_volume": "4 mL",
            },
        },
    )

    second = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "protocol_template_id": protocol["id"],
            "session_number": 2,
            "execution_parameters": {
                "actual_volume": "5 mL",
            },
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201

    first_data = first.json()
    second_data = second.json()

    assert (
        first_data["protocol_snapshot"]
        == second_data["protocol_snapshot"]
    )

    assert (
        first_data["execution_parameters"]["actual_volume"]
        == "4 mL"
    )

    assert (
        second_data["execution_parameters"]["actual_volume"]
        == "5 mL"
    )


def test_treatment_without_protocol_has_no_snapshot(client):
    visit = create_visit(client)

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "ACS",
            "execution_parameters": {
                "documentation": "manual entry",
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["protocol_template_id"] is None
    assert data["protocol_snapshot"] is None

    assert (
        data["execution_parameters"]["documentation"]
        == "manual entry"
    )