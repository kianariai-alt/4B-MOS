"""Real SQLite contention using independent connections, never StaticPool threads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import sqlite3

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from backend.app.db.transactions import ClinicalWriteConflictError
from backend.app.models.audit_log import AuditLog
from backend.app.models.session_finalization import SessionFinalization
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import TreatmentSession
from backend.app.models.treatment_session_component import TreatmentSessionComponent
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.treatment_component import TreatmentComponentCreate
from backend.app.schemas.treatment_session import TreatmentSessionUpdate
from backend.app.schemas.treatment_session_component import (
    TreatmentSessionComponentCreate, TreatmentSessionComponentUpdate,
)
from backend.app.services.session_workflow import SessionWorkflowService
from backend.app.services.treatment_component import TreatmentComponentService, TreatmentComponentLockedError
from backend.app.services.treatment_session import TreatmentSessionService, TreatmentSessionConflictError
from backend.app.services.treatment_session_component import (
    TreatmentSessionComponentService, TreatmentSessionComponentLockedError,
)
from backend.tests.test_clinical_atomic_writes import clinical_context


@pytest.fixture
def concurrent_engine(tmp_path, clinical_context, db_session):
    path = tmp_path / "clinical.sqlite"
    source = db_session.get_bind().raw_connection()
    try:
        with sqlite3.connect(path) as destination:
            source.driver_connection.backup(destination)
    finally:
        source.close()
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.1})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    engine.dispose()


@pytest.mark.parametrize("first,second,rejected", [
    ("start", "plan", TreatmentComponentLockedError),
    ("plan", "start", None),
    ("complete", "administration", TreatmentSessionComponentLockedError),
    ("administration", "complete", None),
    ("complete", "documentation", TreatmentSessionConflictError),
    ("documentation", "complete", None),
    ("complete", "administration_update", TreatmentSessionComponentLockedError),
    ("complete", "administration_delete", TreatmentSessionComponentLockedError),
    ("administration_update", "complete", None),
    ("administration_delete", "complete", None),
])
def test_overlapping_commands_lock_until_audit_commit(
    concurrent_engine, clinical_context, monkeypatch, first, second, rejected,
):
    treatment, material, session = clinical_context
    session_id = session["id"]
    with Session(concurrent_engine) as db:
        SessionWorkflowService.transition(db, session_id, "checked_in")
        SessionWorkflowService.transition(db, session_id, "ready")
        if "start" not in {first, second}:
            SessionWorkflowService.transition(db, session_id, "in_treatment")
        component_id = None
        if {first, second} & {"administration_update", "administration_delete"}:
            component_id = TreatmentSessionComponentService.create_component(
                db, session_id,
                TreatmentSessionComponentCreate(material_id=material["id"], actual_amount="2"),
            ).id
        treatment_timestamp = db.get(Treatment, treatment["id"]).updated_at

    def command(db, name):
        if name == "administration_update":
            return TreatmentSessionComponentService.update_component(
                db, session_id, component_id,
                TreatmentSessionComponentUpdate(actual_amount="4"),
            )
        if name == "administration_delete":
            return TreatmentSessionComponentService.delete_component(db, session_id, component_id)
        if name in {"start", "complete"}:
            return SessionWorkflowService.transition(
                db, session_id, "in_treatment" if name == "start" else "completed",
            )
        if name == "plan":
            return TreatmentComponentService.create_component(
                db, treatment["id"], TreatmentComponentCreate(material_id=material["id"]),
            )
        if name == "documentation":
            return TreatmentSessionService.update_session(
                db, session_id, TreatmentSessionUpdate(notes="concurrent documentation"),
            )
        return TreatmentSessionComponentService.create_component(
            db, session_id,
            TreatmentSessionComponentCreate(material_id=material["id"], actual_amount="3"),
        )

    entered, release = Event(), Event()
    original = AuditLogRepository.create

    def pause_after_audit(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5), "test failed to release the writer"
        return result

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(pause_after_audit))

    def leader():
        with Session(concurrent_engine) as db:
            command(db, first)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(leader)
        try:
            assert entered.wait(5), "writer did not reach audit"
            with Session(concurrent_engine) as db:
                with pytest.raises(ClinicalWriteConflictError):
                    command(db, second)
                assert not db.in_transaction()
        finally:
            release.set()
        future.result(timeout=5)

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(original))
    with Session(concurrent_engine) as db:
        before = db.scalar(select(func.count()).select_from(AuditLog))
        if rejected:
            with pytest.raises(rejected):
                command(db, second)
            assert db.scalar(select(func.count()).select_from(AuditLog)) == before
        else:
            command(db, second)
        current = db.get(TreatmentSession, session_id)
        assert current.status == ("in_progress" if "start" in {first, second} else "completed")
        assert db.get(Treatment, treatment["id"]).updated_at == treatment_timestamp
        if first == "administration":
            assert db.scalar(select(func.count()).select_from(TreatmentSessionComponent)) == 1
        if first == "documentation":
            assert current.notes == "concurrent documentation"
        if first == "administration_update":
            assert db.get(TreatmentSessionComponent, component_id).actual_amount == 4
        if first == "administration_delete":
            assert db.get(TreatmentSessionComponent, component_id) is None
        if "complete" in {first, second}:
            evidence = db.get(SessionFinalization, session_id).payload
            assert evidence["session"]["status"] == "completed"
            if first == "administration_update":
                assert float(evidence["administrations"][0]["actual_amount"]) == 4
            if first == "administration_delete":
                assert evidence["administrations"] == []
            if first == "documentation":
                assert evidence["session"]["notes"] == "concurrent documentation"


def test_failed_writer_releases_lock_and_rolls_back_audit(
    concurrent_engine, clinical_context, monkeypatch,
):
    session_id = clinical_context[2]["id"]
    original = AuditLogRepository.create
    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("audit failure")
    with Session(concurrent_engine) as db:
        before = db.scalar(select(func.count()).select_from(AuditLog))
        monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_after_audit))
        with pytest.raises(RuntimeError, match="audit failure"):
            TreatmentSessionService.update_session(db, session_id, TreatmentSessionUpdate(notes="failed"))
    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(original))
    with Session(concurrent_engine) as other:
        assert other.get(TreatmentSession, session_id).notes is None
        assert other.scalar(select(func.count()).select_from(AuditLog)) == before
        TreatmentSessionService.update_session(other, session_id, TreatmentSessionUpdate(notes="saved"))
    with Session(concurrent_engine) as observer:
        assert observer.get(TreatmentSession, session_id).notes == "saved"


def test_stale_identity_map_cannot_edit_completed_session(concurrent_engine, clinical_context):
    session_id = clinical_context[2]["id"]
    with Session(concurrent_engine) as setup:
        for status in ["checked_in", "ready", "in_treatment"]:
            SessionWorkflowService.transition(setup, session_id, status)
    with Session(concurrent_engine, expire_on_commit=False) as stale:
        old = stale.get(TreatmentSession, session_id)
        stale.commit()
        with Session(concurrent_engine) as other:
            SessionWorkflowService.transition(other, session_id, "completed")
        assert old.status == "in_progress"
        with pytest.raises(TreatmentSessionConflictError):
            TreatmentSessionService.update_session(
                stale, session_id, TreatmentSessionUpdate(notes="must not persist"),
            )
        assert stale.get(TreatmentSession, session_id).notes is None


def test_lock_timeout_is_http_conflict():
    # Exercise the application's actual registered handler without authentication
    # or database dependencies obscuring the response contract.
    from backend.app.main import create_application
    from fastapi.testclient import TestClient
    application = create_application()
    def endpoint():
        raise ClinicalWriteConflictError("Reload before retrying.")
    application.add_api_route("/test-conflict", endpoint, methods=["GET"])
    with TestClient(application) as api:
        response = api.get("/test-conflict")
    assert response.status_code == 409
    assert response.json() == {"detail": "Reload before retrying."}
