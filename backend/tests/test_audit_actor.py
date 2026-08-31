from backend.app.models.user import User
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.schemas.treatment_session import (
    TreatmentSessionCreate,
)
from backend.app.services.treatment_session import (
    TreatmentSessionService,
)


def test_session_audit_log_records_actor(
    client,
    db_session,
):
    user_response = client.post(
        "/api/v1/users",
        json={
            "username": "auditdoctor",
            "display_name": "Audit Doctor",
            "password": "StrongPass123",
            "role": "physician",
        },
    )

    assert user_response.status_code == 201

    user = db_session.get(
        User,
        user_response.json()["id"],
    )

    assert user is not None

    patient_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "AUDIT-PAT-001",
            "first_name": "Audit",
            "last_name": "Patient",
        },
    )

    assert patient_response.status_code == 201

    patient = patient_response.json()

    visit_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        json={
            "body_region": "Knee",
        },
    )

    assert visit_response.status_code == 201

    visit = visit_response.json()

    treatment_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert treatment_response.status_code == 201

    treatment = treatment_response.json()

    treatment_session = (
        TreatmentSessionService.create_session(
            db_session,
            treatment["id"],
            TreatmentSessionCreate(
                session_number=1,
            ),
            actor=user,
        )
    )

    logs = AuditLogRepository.list_by_entity(
        db_session,
        entity_type="treatment_session",
        entity_id=treatment_session.id,
    )

    assert len(logs) == 1

    audit_log = logs[0]

    assert audit_log.actor_user_id == user.id
    assert audit_log.actor_username == "auditdoctor"
    assert audit_log.actor_display_name == "Audit Doctor"
    assert audit_log.actor_role == "physician"