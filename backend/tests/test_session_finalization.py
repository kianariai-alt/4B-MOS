from copy import deepcopy

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.orthobiologic_material import OrthobiologicMaterial
from backend.app.models.session_finalization import SessionFinalization
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import TreatmentSession
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.treatment_component import TreatmentComponentCreate
from backend.app.schemas.treatment_session_component import TreatmentSessionComponentCreate
from backend.app.services.session_finalization import SessionFinalizationService, evidence_digest
from backend.app.services.session_workflow import SessionWorkflowService, SessionWorkflowConflictError
from backend.app.services.treatment_component import TreatmentComponentService
from backend.app.services.treatment_session_component import TreatmentSessionComponentService
from backend.tests.test_clinical_atomic_writes import clinical_context
from backend.tests.test_treatment_session_clinical_summary import create_user_and_login


@pytest.fixture
def active_session(db_session, clinical_context):
    treatment, material, session = clinical_context
    plan_id = TreatmentComponentService.create_component(
        db_session, treatment["id"],
        TreatmentComponentCreate(material_id=material["id"], planned_amount="3", unit="ml"),
    ).id
    for status in ["checked_in", "ready", "in_treatment"]:
        SessionWorkflowService.transition(db_session, session["id"], status)
    TreatmentSessionComponentService.create_component(
        db_session, session["id"],
        TreatmentSessionComponentCreate(
            material_id=material["id"], treatment_component_id=plan_id,
            actual_amount="2", unit="ml", lot_number="LOT-001", expiry_date="2027-01-01",
            preparation_parameters={"cycles": 3}, notes="آزمایشی",
        ),
    )
    return session["id"]


def test_evidence_survives_catalog_changes_discharge_and_actor_rename(
    client, admin_headers, db_session, active_session, clinical_context,
):
    session_id = active_session
    response = client.patch(f"/api/v1/treatment-sessions/{session_id}/workflow", headers=admin_headers,
                            json={"operational_status": "completed"})
    assert response.status_code == 200
    url = f"/api/v1/treatment-sessions/{session_id}/finalization"
    first = client.get(url, headers=admin_headers)
    assert first.status_code == 200
    evidence = first.json()
    payload = evidence["payload"]
    assert evidence_digest(payload) == evidence["sha256"]
    assert payload["schema_version"] == 1
    assert payload["actor"]["actor_username"] == "testadmin"
    assert payload["session"]["status"] == "completed"
    assert payload["session"]["operational_status"] == "completed"
    assert payload["administrations"][0]["lot_number"] == "LOT-001"
    assert payload["administrations"][0]["expiry_date"] == "2027-01-01"
    assert payload["administrations"][0]["preparation_parameters"] == {"cycles": 3}
    assert payload["completion_check_before_transition"]["warning_count"] > 0
    assert payload["materials"][0]["requires_lot_tracking"] is False
    state_event = db_session.scalar(select(AuditLog).where(
        AuditLog.entity_id == session_id, AuditLog.event_type == "state_transition", AuditLog.to_state == "completed",
    ))
    assert state_event.event_data["finalization_sha256"] == evidence["sha256"]
    material = db_session.get(OrthobiologicMaterial, clinical_context[1]["id"])
    material.name = "Renamed later"
    material.requires_lot_tracking = True
    db_session.get(Treatment, clinical_context[0]["id"]).notes = "later parent edit"
    db_session.scalar(select(User).where(User.username == "testadmin")).display_name = "Renamed actor"
    db_session.commit()
    SessionWorkflowService.transition(db_session, session_id, "discharged")
    assert client.get(url, headers=admin_headers).json() == evidence
    with pytest.raises(SessionWorkflowConflictError):
        SessionWorkflowService.transition(db_session, session_id, "completed")
    assert db_session.scalar(select(func.count()).select_from(SessionFinalization)) == 1


@pytest.mark.parametrize("failure", ["snapshot", "audit", "commit"])
def test_completion_snapshot_and_audits_rollback_together(db_session, active_session, monkeypatch, failure):
    before = db_session.scalar(select(func.count()).select_from(AuditLog))
    original_capture = SessionFinalizationService.capture
    original_audit = AuditLogRepository.create
    def fail_capture(*args, **kwargs):
        original_capture(*args, **kwargs)
        raise RuntimeError("injected snapshot failure")
    def fail_audit(*args, **kwargs):
        original_audit(*args, **kwargs)
        raise RuntimeError("injected audit failure")
    def fail_commit():
        raise RuntimeError("injected commit failure")
    if failure == "snapshot":
        monkeypatch.setattr(SessionFinalizationService, "capture", staticmethod(fail_capture))
    elif failure == "audit":
        monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))
    else:
        monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="injected"):
        SessionWorkflowService.transition(db_session, active_session, "completed")
    with Session(db_session.get_bind()) as observer:
        session = observer.get(TreatmentSession, active_session)
        assert session.status == "in_progress"
        assert session.completed_at is None
        assert observer.get(SessionFinalization, active_session) is None
        assert observer.scalar(select(func.count()).select_from(AuditLog)) == before


@pytest.mark.parametrize("operation", ["update", "delete", "duplicate", "delete_session"])
def test_evidence_write_and_parent_deletion_guards(db_session, active_session, operation):
    SessionWorkflowService.transition(db_session, active_session, "completed")
    original = db_session.get(SessionFinalization, active_session)
    expected = deepcopy(original.payload)
    if operation == "update":
        original.payload = {"replaced": True}
    elif operation == "delete":
        db_session.delete(original)
    elif operation == "duplicate":
        db_session.expunge(original)
        db_session.add(SessionFinalization(session_id=active_session, captured_at=original.captured_at,
                                          payload=expected, sha256=original.sha256))
    with pytest.raises((ValueError, IntegrityError)):
        if operation == "delete_session":
            db_session.execute(delete(TreatmentSession).where(TreatmentSession.id == active_session))
        db_session.commit()
    db_session.rollback()
    assert db_session.get(SessionFinalization, active_session).payload == expected


def test_checksum_detects_out_of_band_payload_edit(client, admin_headers, db_session, active_session):
    SessionWorkflowService.transition(db_session, active_session, "completed")
    db_session.execute(update(SessionFinalization).where(SessionFinalization.session_id == active_session)
                       .values(payload={"session": {"id": active_session}, "tampered": True}))
    db_session.commit()
    response = client.get(f"/api/v1/treatment-sessions/{active_session}/finalization", headers=admin_headers)
    assert response.status_code == 409
    assert "payload" not in response.json()


@pytest.mark.parametrize("state", ["planned", "completed", "cancelled"])
def test_missing_evidence_is_never_backfilled(client, admin_headers, db_session, clinical_context, state):
    session_id = clinical_context[2]["id"]
    session = db_session.get(TreatmentSession, session_id)
    session.status = state
    db_session.commit()
    response = client.get(f"/api/v1/treatment-sessions/{session_id}/finalization", headers=admin_headers)
    assert response.status_code == 404
    assert db_session.get(SessionFinalization, session_id) is None


def test_read_requires_auth_and_viewer_cannot_rewrite(client, admin_headers, db_session, active_session):
    SessionWorkflowService.transition(db_session, active_session, "completed")
    url = f"/api/v1/treatment-sessions/{active_session}/finalization"
    assert client.get(url).status_code == 401
    headers = create_user_and_login(client, admin_headers, username="evidenceviewer", role="viewer")
    assert client.get(url, headers=headers).status_code == 200
    for method in [client.post, client.patch, client.put, client.delete]:
        assert method(url, headers=admin_headers).status_code == 405


@pytest.mark.parametrize("scenario", ["blocked", "no_plan", "cancelled"])
def test_capture_only_on_successful_completion(db_session, clinical_context, scenario):
    treatment, material, session = clinical_context
    if scenario == "blocked":
        TreatmentComponentService.create_component(db_session, treatment["id"],
            TreatmentComponentCreate(material_id=material["id"], planned_amount="3"))
    for status in ["checked_in", "ready", "in_treatment"]:
        SessionWorkflowService.transition(db_session, session["id"], status)
    if scenario == "blocked":
        with pytest.raises(SessionWorkflowConflictError):
            SessionWorkflowService.transition(db_session, session["id"], "completed")
    else:
        SessionWorkflowService.transition(db_session, session["id"],
                                         "cancelled" if scenario == "cancelled" else "completed")
    record = db_session.get(SessionFinalization, session["id"])
    if scenario == "no_plan":
        assert record.payload["administrations"] == []
        assert record.payload["planned_components"] == []
        assert record.payload["completion_check_before_transition"]["can_complete"] is True
        assert record.payload["actor"]["actor_user_id"] is None
    else:
        assert record is None
