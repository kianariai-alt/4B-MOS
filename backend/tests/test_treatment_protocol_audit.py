from backend.app.repositories.audit_log import (
    AuditLogRepository,
)


def create_patient_and_visit(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "AUD-TP-001",
            "first_name": "Audit",
            "last_name": "Treatment",
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

    return visit_response.json()


def test_treatment_create_is_audited(
    client,
    admin_headers,
    db_session,
):
    visit = create_patient_and_visit(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    treatment = response.json()

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="treatment",
        entity_id=treatment["id"],
    )

    assert len(logs) == 1

    log = logs[0]

    assert (
        log.event_type
        == "treatment_created"
    )

    assert log.from_state is None

    assert (
        log.to_state
        == "planned"
    )

    assert (
        log.actor_username
        == "testadmin"
    )

    assert (
        log.actor_role
        == "admin"
    )


def test_treatment_update_is_audited(
    client,
    admin_headers,
    db_session,
):
    visit = create_patient_and_visit(
        client,
        admin_headers,
    )

    create_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "ACS",
        },
    )

    assert create_response.status_code == 201

    treatment = create_response.json()

    update_response = client.patch(
        f"/api/v1/treatments/{treatment['id']}",
        headers=admin_headers,
        json={
            "notes": "Updated treatment note",
        },
    )

    assert update_response.status_code == 200

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="treatment",
        entity_id=treatment["id"],
    )

    assert len(logs) == 2

    log = logs[1]

    assert (
        log.event_type
        == "treatment_updated"
    )

    assert (
        log.event_data[
            "changed_fields"
        ]
        == ["notes"]
    )

    assert log.from_state is None
    assert log.to_state is None

    assert (
        log.actor_username
        == "testadmin"
    )


def test_treatment_status_change_is_audited(
    client,
    admin_headers,
    db_session,
):
    visit = create_patient_and_visit(
        client,
        admin_headers,
    )

    create_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "PRGF",
        },
    )

    assert create_response.status_code == 201

    treatment = create_response.json()

    update_response = client.patch(
        f"/api/v1/treatments/{treatment['id']}",
        headers=admin_headers,
        json={
            "status": "completed",
        },
    )

    assert update_response.status_code == 200

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="treatment",
        entity_id=treatment["id"],
    )

    assert len(logs) == 2

    log = logs[1]

    assert (
        log.event_type
        == "treatment_updated"
    )

    assert (
        log.from_state
        == "planned"
    )

    assert (
        log.to_state
        == "completed"
    )

    assert (
        "status"
        in log.event_data[
            "changed_fields"
        ]
    )


def test_protocol_create_is_audited(
    client,
    admin_headers,
    db_session,
):
    response = client.post(
        "/api/v1/protocols",
        headers=admin_headers,
        json={
            "code": "AUD-PROT-001",
            "name": "Audit PRP Protocol",
            "treatment_type": "PRP",
            "version": "1.0",
        },
    )

    assert response.status_code == 201

    protocol = response.json()

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="protocol",
        entity_id=protocol["id"],
    )

    assert len(logs) == 1

    log = logs[0]

    assert (
        log.event_type
        == "protocol_created"
    )

    assert log.from_state is None
    assert log.to_state == "active"

    assert (
        log.actor_username
        == "testadmin"
    )


def test_protocol_deactivation_is_audited(
    client,
    admin_headers,
    db_session,
):
    create_response = client.post(
        "/api/v1/protocols",
        headers=admin_headers,
        json={
            "code": "AUD-PROT-002",
            "name": "Deactivate Protocol",
            "treatment_type": "ACS",
            "version": "1.0",
        },
    )

    assert create_response.status_code == 201

    protocol = create_response.json()

    response = client.delete(
        f"/api/v1/protocols/{protocol['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="protocol",
        entity_id=protocol["id"],
    )

    assert len(logs) == 2

    log = logs[1]

    assert (
        log.event_type
        == "protocol_deactivated"
    )

    assert (
        log.from_state
        == "active"
    )

    assert (
        log.to_state
        == "inactive"
    )

    assert (
        log.actor_username
        == "testadmin"
    )


def test_physician_is_recorded_as_treatment_actor(
    client,
    admin_headers,
    db_session,
):
    visit = create_patient_and_visit(
        client,
        admin_headers,
    )

    create_user_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "auditphysician",
            "display_name": "Audit Physician",
            "password": "StrongPass123",
            "role": "physician",
        },
    )

    assert (
        create_user_response.status_code
        == 201
    )

    physician = create_user_response.json()

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "auditphysician",
            "password": "StrongPass123",
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    physician_headers = {
        "Authorization": f"Bearer {token}",
    }

    treatment_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=physician_headers,
        json={
            "treatment_type": "PL",
        },
    )

    assert treatment_response.status_code == 201

    treatment = treatment_response.json()

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="treatment",
        entity_id=treatment["id"],
    )

    assert len(logs) == 1

    log = logs[0]

    assert (
        log.actor_user_id
        == physician["id"]
    )

    assert (
        log.actor_username
        == "auditphysician"
    )

    assert (
        log.actor_display_name
        == "Audit Physician"
    )

    assert (
        log.actor_role
        == "physician"
    )