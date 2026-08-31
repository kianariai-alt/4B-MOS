from backend.app.repositories.audit_log import (
    AuditLogRepository,
)


def test_patient_create_records_actor(
    client,
    admin_headers,
    db_session,
):
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "AUD-PAT-001",
            "first_name": "Audit",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    patient = response.json()

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="patient",
        entity_id=patient["id"],
    )

    assert len(logs) == 1

    log = logs[0]

    assert (
        log.event_type
        == "patient_created"
    )

    assert (
        log.actor_username
        == "testadmin"
    )

    assert log.actor_role == "admin"

    assert log.from_state is None
    assert log.to_state == "active"


def test_patient_update_records_changed_fields(
    client,
    admin_headers,
    db_session,
):
    create_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "AUD-PAT-002",
            "first_name": "Before",
            "last_name": "Update",
        },
    )

    assert create_response.status_code == 201

    patient = create_response.json()

    update_response = client.patch(
        f"/api/v1/patients/{patient['id']}",
        headers=admin_headers,
        json={
            "first_name": "After",
        },
    )

    assert update_response.status_code == 200

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="patient",
        entity_id=patient["id"],
    )

    assert len(logs) == 2

    update_log = logs[1]

    assert (
        update_log.event_type
        == "patient_updated"
    )

    assert (
        update_log.event_data[
            "changed_fields"
        ]
        == ["first_name"]
    )

    assert (
        update_log.actor_username
        == "testadmin"
    )


def test_patient_deactivation_is_audited(
    client,
    admin_headers,
    db_session,
):
    create_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "AUD-PAT-003",
            "first_name": "Deactivate",
            "last_name": "Patient",
        },
    )

    assert create_response.status_code == 201

    patient = create_response.json()

    response = client.delete(
        f"/api/v1/patients/{patient['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="patient",
        entity_id=patient["id"],
    )

    assert len(logs) == 2

    log = logs[1]

    assert (
        log.event_type
        == "patient_deactivated"
    )

    assert log.from_state == "active"
    assert log.to_state == "inactive"

    assert (
        log.actor_username
        == "testadmin"
    )


def test_visit_create_records_actor(
    client,
    admin_headers,
    db_session,
):
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "AUD-VIS-001",
            "first_name": "Visit",
            "last_name": "Patient",
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

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="visit",
        entity_id=visit["id"],
    )

    assert len(logs) == 1

    log = logs[0]

    assert (
        log.event_type
        == "visit_created"
    )

    assert (
        log.actor_username
        == "testadmin"
    )

    assert log.actor_role == "admin"


def test_visit_update_records_changed_fields(
    client,
    admin_headers,
    db_session,
):
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "AUD-VIS-002",
            "first_name": "Visit",
            "last_name": "Update",
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

    update_response = client.patch(
        f"/api/v1/visits/{visit['id']}",
        headers=admin_headers,
        json={
            "notes": "Follow-up note",
        },
    )

    assert update_response.status_code == 200

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="visit",
        entity_id=visit["id"],
    )

    assert len(logs) == 2

    log = logs[1]

    assert (
        log.event_type
        == "visit_updated"
    )

    assert (
        log.event_data[
            "changed_fields"
        ]
        == ["notes"]
    )

    assert (
        log.actor_username
        == "testadmin"
    )