"""Failure-injection tests: clinical records must never outlive their audit."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.treatment_component import TreatmentComponent
from backend.app.models.treatment_session_component import TreatmentSessionComponent
from backend.app.models.treatment_session import TreatmentSession
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.treatment_component import (
    TreatmentComponentCreate, TreatmentComponentUpdate,
)
from backend.app.schemas.treatment_session_component import (
    TreatmentSessionComponentCreate, TreatmentSessionComponentUpdate,
)
from backend.app.services.treatment_component import TreatmentComponentService
from backend.app.services.treatment_session_component import TreatmentSessionComponentService
from backend.app.services.session_workflow import SessionWorkflowService
from backend.tests.test_treatment_session_components import (
    create_treatment, create_material, create_session, ensure_in_treatment,
)


@pytest.fixture
def clinical_context(client, admin_headers):
    treatment = create_treatment(client, admin_headers)
    material = create_material(client, admin_headers, code="ACS", name="ACS")
    session = create_session(client, admin_headers, treatment_id=treatment["id"])
    return treatment, material, session


@pytest.mark.parametrize("kind", ["plan", "administration"])
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("failure", ["before_audit", "after_audit_flush", "commit"])
def test_component_and_audit_rollback_together(
    client, admin_headers, db_session, clinical_context, monkeypatch,
    kind, operation, failure,
):
    treatment, material, session = clinical_context
    if kind == "plan":
        service = TreatmentComponentService
        model = TreatmentComponent
        parent_id = treatment["id"]
        create_payload = TreatmentComponentCreate(
            material_id=material["id"], planned_amount="3.0",
        )
        update_payload = TreatmentComponentUpdate(planned_amount="5.0")
        amount_field = "planned_amount"
    else:
        ensure_in_treatment(client, admin_headers, session["id"])
        service = TreatmentSessionComponentService
        model = TreatmentSessionComponent
        parent_id = session["id"]
        create_payload = TreatmentSessionComponentCreate(
            material_id=material["id"], actual_amount="3.0",
        )
        update_payload = TreatmentSessionComponentUpdate(actual_amount="5.0")
        amount_field = "actual_amount"

    component_id = None
    if operation != "create":
        component_id = service.create_component(db_session, parent_id, create_payload).id
    audit_count = db_session.scalar(select(func.count()).select_from(AuditLog))
    original_audit = AuditLogRepository.create

    def fail_audit(*args, **kwargs):
        if failure == "after_audit_flush":
            original_audit(*args, **kwargs)
        raise RuntimeError("injected persistence failure")

    def fail_commit():
        raise RuntimeError("injected persistence failure")

    if failure == "commit":
        monkeypatch.setattr(db_session, "commit", fail_commit)
    else:
        monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))

    with pytest.raises(RuntimeError, match="injected persistence failure"):
        if operation == "create":
            service.create_component(db_session, parent_id, create_payload)
        elif operation == "update":
            service.update_component(db_session, parent_id, component_id, update_payload)
        else:
            service.delete_component(db_session, parent_id, component_id)

    assert not db_session.in_transaction()
    # Observe committed state from a fresh Session, not the failed identity map.
    with Session(bind=db_session.get_bind()) as observer:
        rows = list(observer.scalars(select(model)))
        assert len(rows) == (0 if operation == "create" else 1)
        if rows:
            assert rows[0].id == component_id
            assert getattr(rows[0], amount_field) == Decimal("3.0")
        assert observer.scalar(select(func.count()).select_from(AuditLog)) == audit_count


@pytest.mark.parametrize("target", ["in_treatment", "completed", "cancelled"])
def test_workflow_rolls_back_status_timestamps_and_both_audits(
    client, admin_headers, db_session, clinical_context, monkeypatch, target,
):
    treatment, material, session = clinical_context
    session_id = session["id"]
    SessionWorkflowService.transition(db_session, session_id, "checked_in")
    SessionWorkflowService.transition(db_session, session_id, "ready")
    if target != "in_treatment":
        SessionWorkflowService.transition(db_session, session_id, "in_treatment")
        TreatmentSessionComponentService.create_component(
            db_session, session_id,
            TreatmentSessionComponentCreate(material_id=material["id"], actual_amount="3"),
        )
    before = db_session.get(TreatmentSession, session_id)
    expected = (before.status, before.operational_status, before.started_at, before.completed_at)
    audit_count = db_session.scalar(select(func.count()).select_from(AuditLog))
    original_audit = AuditLogRepository.create
    calls = []

    def fail_second_audit(*args, **kwargs):
        calls.append(kwargs["event_type"])
        result = original_audit(*args, **kwargs)
        if len(calls) == 2:
            raise RuntimeError("second audit failed")
        return result

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_second_audit))
    with pytest.raises(RuntimeError, match="second audit failed"):
        SessionWorkflowService.transition(db_session, session_id, target)

    assert calls == ["state_transition", "operational_transition"]
    assert not db_session.in_transaction()
    with Session(bind=db_session.get_bind()) as observer:
        actual = observer.get(TreatmentSession, session_id)
        assert (actual.status, actual.operational_status, actual.started_at, actual.completed_at) == expected
        assert observer.scalar(select(func.count()).select_from(AuditLog)) == audit_count
