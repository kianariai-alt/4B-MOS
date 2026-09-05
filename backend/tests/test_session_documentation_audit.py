"""Session documentation is attributed, atomic and immutable after closure."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.treatment_session import TreatmentSession
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.treatment_session import TreatmentSessionCreate, TreatmentSessionUpdate
from backend.app.services.treatment_session import TreatmentSessionService
from backend.tests.test_clinical_atomic_writes import clinical_context
from backend.tests.test_treatment_session_components import ensure_in_treatment


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("failure", ["before_audit", "after_audit_flush", "commit"])
def test_session_documentation_rolls_back(
    db_session, clinical_context, monkeypatch, operation, failure,
):
    treatment, _, session = clinical_context
    session_id = session["id"]
    original = db_session.get(TreatmentSession, session_id)
    notes_before = original.notes
    audits_before = db_session.scalar(select(func.count()).select_from(AuditLog))
    original_audit = AuditLogRepository.create

    def fail_audit(*args, **kwargs):
        if failure == "after_audit_flush":
            original_audit(*args, **kwargs)
        raise RuntimeError("injected audit failure")

    def fail_commit():
        raise RuntimeError("injected commit failure")

    if failure == "commit":
        monkeypatch.setattr(db_session, "commit", fail_commit)
    else:
        monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))
    with pytest.raises(RuntimeError, match="injected"):
        if operation == "create":
            TreatmentSessionService.create_session(
                db_session, treatment["id"], TreatmentSessionCreate(session_number=2),
            )
        else:
            TreatmentSessionService.update_session(
                db_session, session_id, TreatmentSessionUpdate(notes="new clinical note"),
            )
    assert not db_session.in_transaction()
    with Session(bind=db_session.get_bind()) as observer:
        assert observer.scalar(select(func.count()).select_from(TreatmentSession)) == 1
        assert observer.get(TreatmentSession, session_id).notes == notes_before
        assert observer.scalar(select(func.count()).select_from(AuditLog)) == audits_before


def test_documentation_audit_records_actor_before_after_and_json_values(
    client, admin_headers, db_session, clinical_context,
):
    _, _, session = clinical_context
    session_id = session["id"]
    ensure_in_treatment(client, admin_headers, session_id)
    payload = {
        "notes": "documented during treatment",
        "outcome_summary": "response recorded",
        "adverse_events": "none observed",
        "scheduled_at": "2026-09-03T10:00:00",
        "execution_parameters": {"method": "test", "values": [1, 2]},
    }
    response = client.patch(
        f"/api/v1/treatment-sessions/{session_id}", headers=admin_headers, json=payload,
    )
    assert response.status_code == 200
    with Session(bind=db_session.get_bind()) as observer:
        log = observer.scalar(select(AuditLog).where(
            AuditLog.entity_id == session_id, AuditLog.event_type == "session_updated",
        ))
        assert log.actor_username == "testadmin"
        assert log.actor_role == "admin"
        assert log.from_state == log.to_state == "in_progress"
        assert log.event_data["changed_fields"] == sorted(payload)
        assert log.event_data["before"] == dict.fromkeys(payload)
        assert log.event_data["after"] == payload

    # A repeated identical request and an empty PATCH create no fake edits.
    for value in (payload, {}):
        response = client.patch(
            f"/api/v1/treatment-sessions/{session_id}", headers=admin_headers, json=value,
        )
        assert response.status_code == 200
    with Session(bind=db_session.get_bind()) as observer:
        assert observer.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_id == session_id, AuditLog.event_type == "session_updated",
        )) == 1

    response = client.patch(
        f"/api/v1/treatment-sessions/{session_id}", headers=admin_headers,
        json={"notes": None, "execution_parameters": None},
    )
    assert response.status_code == 200
    with Session(bind=db_session.get_bind()) as observer:
        logs = list(observer.scalars(select(AuditLog).where(
            AuditLog.entity_id == session_id, AuditLog.event_type == "session_updated",
        )))
        assert len(logs) == 2
        cleared = next(log for log in logs if log.event_data["after"].get("notes") is None)
        assert cleared.event_data["before"]["notes"] == payload["notes"]
        assert cleared.event_data["after"] == {"notes": None, "execution_parameters": None}


@pytest.mark.parametrize("payload", [
    {"session_number": None}, {"operational_status": "completed"},
    {"treatment_id": "another-treatment"}, {"unknown_field": "value"},
])
def test_invalid_session_update_is_rejected(client, admin_headers, clinical_context, payload):
    _, _, session = clinical_context
    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}", headers=admin_headers, json=payload,
    )
    assert response.status_code == 422


@pytest.mark.parametrize("state", ["completed", "discharged", "cancelled"])
def test_closed_session_cannot_be_rewritten_and_failed_patch_is_not_audited(
    client, admin_headers, db_session, clinical_context, state,
):
    _, _, session = clinical_context
    session_id = session["id"]
    ensure_in_treatment(client, admin_headers, session_id)
    targets = ["cancelled"] if state == "cancelled" else ["completed"]
    if state == "discharged":
        targets.append("discharged")
    for target in targets:
        response = client.patch(
            f"/api/v1/treatment-sessions/{session_id}/workflow",
            headers=admin_headers, json={"operational_status": target},
        )
        assert response.status_code == 200
    before = client.get(f"/api/v1/treatment-sessions/{session_id}", headers=admin_headers).json()
    for payload in ({"notes": "changed", "adverse_events": "changed"}, {}):
        response = client.patch(
            f"/api/v1/treatment-sessions/{session_id}", headers=admin_headers, json=payload,
        )
        assert response.status_code == 409
    after = client.get(f"/api/v1/treatment-sessions/{session_id}", headers=admin_headers).json()
    assert after == before
    with Session(bind=db_session.get_bind()) as observer:
        assert observer.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_id == session_id, AuditLog.event_type == "session_updated",
        )) == 0
