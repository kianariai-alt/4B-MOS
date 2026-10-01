"""Synthetic integration coverage for administrative intake and consent boundaries."""

from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select, text
from backend.app.models.reception import ReceptionRevision, VisitConsentEvent
from backend.app.models.audit_log import AuditLog
from backend.app.services.reception import ReceptionService
from backend.tests.test_treatment_options_roadmap import (
    create_role_headers,
    create_patient,
    create_visit,
)

pytestmark = pytest.mark.usefixtures("authenticated_admin")


def setup_visit(client):
    patient = create_patient(client, code="RECEPTION-SYNTHETIC")
    visit = create_visit(client, patient["id"], complaint="Synthetic knee complaint")
    return visit, f"/api/v1/visits/{visit['id']}/reception"


def intake(**changes):
    return {
        "patient_reported_complaint": "Synthetic patient statement",
        "expected_version": 0,
        "request_key": "intake-0001",
        **changes,
    }


def consent(**changes):
    return {
        "purpose": "marketing",
        "state": "granted",
        "document_version": "FA-1",
        "evidence_reference": "SYNTHETIC-DOC-001",
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "expected_version": 0,
        "request_key": "consent-0001",
        **changes,
    }


def test_independent_default_consent_and_no_treatment_authorization(client):
    visit, root = setup_visit(client)
    body = client.get(root).json()
    assert body["patient_id"] == visit["patient_id"]
    assert body["intake_version"] == body["consent_version"] == 0
    assert {c["state"] for c in body["consents"]} == {"unknown"}
    assert len(body["consents"]) == 5
    assert body["authorizes_treatment"] is False
    assert client.get("/api/v1/visits/missing/reception").status_code == 404


def test_operator_intake_retry_conflict_and_read_only_clinical_boundary(
    client, db_session
):
    visit, root = setup_visit(client)
    headers = create_role_headers(
        client, username="reception_operator", role="operator"
    )
    data = intake(phone="SYNTHETIC-PHONE")
    first = client.post(root + "/intakes", headers=headers, json=data)
    assert first.status_code == 201, first.text
    retry = client.post(root + "/intakes", headers=headers, json=data)
    assert retry.json()["id"] == first.json()["id"]
    assert (
        client.post(
            root + "/intakes", headers=headers, json={**data, "care_goal": "changed"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            root + "/intakes", headers=headers, json=intake(request_key="intake-0002")
        ).status_code
        == 409
    )
    updated = client.post(
        root + "/intakes",
        headers=headers,
        json=intake(expected_version=1, request_key="intake-0002"),
    )
    assert updated.status_code == 201
    assert updated.json()["version"] == 2
    assert len(client.get(root + "/intakes", headers=headers).json()) == 2
    assert (
        client.post(
            root + "/intakes", headers=headers, json=intake(diagnosis="FORGED")
        ).status_code
        == 422
    )
    assert (
        client.post(
            root + "/intakes", headers=headers, json=intake(state="ready_for_screen")
        ).status_code
        == 422
    )
    assert (
        client.post(
            root + "/intakes",
            headers=headers,
            json=intake(
                assigned_physician_id="missing",
                expected_version=2,
                request_key="intake-0003",
            ),
        ).status_code
        == 409
    )
    assert (
        client.post(
            root + "/intakes",
            headers=headers,
            json=intake(
                assigned_physician_id=first.json()["recorded_by"],
                expected_version=2,
                request_key="intake-0003",
            ),
        ).status_code
        == 409
    )
    audits = list(
        db_session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "reception_revisions")
        )
    )
    assert len(audits) == 2
    assert "SYNTHETIC-PHONE" not in str([a.event_data for a in audits])
    from backend.app.models.visit import Visit

    assert db_session.get(Visit, visit["id"]).diagnosis is None


def test_active_physician_assignment(client):
    _, root = setup_visit(client)
    headers = create_role_headers(client, username="screen_physician", role="physician")
    physician = client.get("/api/v1/auth/me", headers=headers).json()
    response = client.post(
        root + "/intakes",
        json=intake(state="ready_for_screen", assigned_physician_id=physician["id"]),
    )
    assert response.status_code == 201, response.text
    assert response.json()["content"]["state"] == "ready_for_screen"


@pytest.mark.parametrize(
    "role,read_status,write_status",
    [
        ("operator", 200, 201),
        ("physician", 200, 201),
        ("nurse", 200, 403),
        ("viewer", 403, 403),
    ],
)
def test_role_boundaries(client, role, read_status, write_status):
    _, root = setup_visit(client)
    headers = create_role_headers(client, username=f"reception_{role}", role=role)
    assert client.get(root, headers=headers).status_code == read_status
    assert (
        client.post(root + "/intakes", headers=headers, json=intake()).status_code
        == write_status
    )
    assert (
        client.post(root + "/consents", headers=headers, json=consent()).status_code
        == write_status
    )
    assert (
        client.get(root, headers={"Authorization": "Bearer invalid"}).status_code == 401
    )


def test_consent_withdrawal_purpose_isolation_retry_and_closed_visit(
    client, db_session
):
    visit, root = setup_visit(client)
    data = consent()
    first = client.post(root + "/consents", json=data)
    assert first.status_code == 201, first.text
    assert client.post(root + "/consents", json=data).json()["id"] == first.json()["id"]
    assert ReceptionService.consent_granted(db_session, visit["id"], "marketing")
    assert not ReceptionService.consent_granted(
        db_session, visit["id"], "audio_recording"
    )
    assert (
        client.post(
            root + "/consents",
            json=consent(purpose="audio_recording", request_key="consent-0002"),
        ).status_code
        == 409
    )
    from backend.app.models.visit import Visit

    db_session.get(Visit, visit["id"]).status = "closed"
    db_session.commit()
    withdrawal = client.post(
        root + "/consents",
        json=consent(state="withdrawn", expected_version=1, request_key="consent-0002"),
    )
    assert withdrawal.status_code == 201
    assert not ReceptionService.consent_granted(db_session, visit["id"], "marketing")
    assert len(client.get(root + "/consents").json()) == 2
    assert client.post(root + "/intakes", json=intake()).status_code == 409
    with pytest.raises(ValueError):
        ReceptionService.consent_granted(db_session, visit["id"], "invalid")


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed_at": "2026-01-01T12:00:00"},
        {"confirmed_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
        {"purpose": "all"},
        {"state": "unknown"},
        {"evidence_reference": ""},
        {"document_version": " "},
        {"expected_version": True},
        {"diagnosis": "bad"},
    ],
)
def test_invalid_consent_rejected(client, changes):
    _, root = setup_visit(client)
    assert client.post(root + "/consents", json=consent(**changes)).status_code == 422


@pytest.mark.parametrize(
    "model,endpoint,command",
    [(ReceptionRevision, "intakes", intake), (VisitConsentEvent, "consents", consent)],
)
def test_immutability_and_sql_tamper_detection(
    client, db_session, model, endpoint, command
):
    _, root = setup_visit(client)
    created = client.post(root + "/" + endpoint, json=command()).json()
    row = db_session.get(model, created["id"])
    row.request_key = "changed-key"
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    db_session.execute(
        text(f"UPDATE {model.__tablename__} SET request_key = 'forged' WHERE id = :id"),
        {"id": created["id"]},
    )
    db_session.commit()
    assert client.get(root).status_code == 409


def test_legacy_visit_creation_cannot_bypass_reception_diagnosis_boundary(client):
    patient = create_patient(client, code="BOUNDARY-SYNTHETIC")
    headers = create_role_headers(
        client, username="diagnosis_operator", role="operator"
    )
    route = f"/api/v1/patients/{patient['id']}/visits"
    assert (
        client.post(route, headers=headers, json={"diagnosis": "FORGED"}).status_code
        == 403
    )
    assert (
        client.post(
            route, headers=headers, json={"chief_complaint": "Patient statement"}
        ).status_code
        == 201
    )


def test_audit_failure_rolls_back_intake(client, db_session, monkeypatch):
    visit, root = setup_visit(client)
    from backend.app.repositories.audit_log import AuditLogRepository

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(AuditLogRepository, "create", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        client.post(root + "/intakes", json=intake())
    assert (
        list(
            db_session.scalars(
                select(ReceptionRevision).where(
                    ReceptionRevision.visit_id == visit["id"]
                )
            )
        )
        == []
    )


def test_request_key_cannot_replay_another_authors_command(client):
    _, root = setup_visit(client)
    data = consent()
    assert client.post(root + "/consents", json=data).status_code == 201
    headers = create_role_headers(client, username="other_operator", role="operator")
    assert (
        client.post(root + "/consents", json=data, headers=headers).status_code == 409
    )


def test_lock_conflict_is_a_controlled_http_conflict(client, monkeypatch):
    _, root = setup_visit(client)
    from backend.app.db.clinical_record_transactions import (
        ClinicalRecordWriteConflictError,
    )

    def conflict(*args, **kwargs):
        raise ClinicalRecordWriteConflictError("Synthetic competing write")

    monkeypatch.setattr(ReceptionService, "save_intake", conflict)
    assert client.post(root + "/intakes", json=intake()).status_code == 409
