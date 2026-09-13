"""Append-only session amendments preserve evidence, authority and review history."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.session_amendment import (
    SessionAmendment,
    SessionAmendmentReview,
)
from backend.app.models.session_finalization import SessionFinalization
from backend.app.models.user import User
from backend.app.db.transactions import ClinicalWriteConflictError
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.session_amendment import (
    SessionAmendmentCreate,
    SessionAmendmentReviewCreate,
)
from backend.app.services.session_amendment import (
    SessionAmendmentService,
)
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.session_workflow import SessionWorkflowService
from backend.tests.test_clinical_atomic_writes import clinical_context
from backend.tests.test_clinical_concurrency import concurrent_engine
from backend.tests.test_treatment_session_clinical_summary import create_user_and_login


@pytest.fixture
def finalized_session(db_session, clinical_context):
    session_id = clinical_context[2]["id"]
    for target in ("checked_in", "ready", "in_treatment", "completed"):
        SessionWorkflowService.transition(db_session, session_id, target)
    return session_id


def amendment_json(**overrides):
    payload = {
        "amendment_type": "correction",
        "reason_code": "data_entry_error",
        "reason_detail": "The original note contained a transcription error.",
        "statement": "Corrected clinical statement retained as an addendum.",
        "target_reference": "session.notes",
    }
    payload.update(overrides)
    return payload


def create_amendment(client, headers, session_id, **overrides):
    return client.post(
        f"/api/v1/treatment-sessions/{session_id}/amendments",
        headers=headers,
        json=amendment_json(**overrides),
    )


def test_admin_can_create_and_self_approve_without_rewriting_finalization(
    client,
    admin_headers,
    db_session,
    finalized_session,
):
    finalization_url = (
        f"/api/v1/treatment-sessions/{finalized_session}/finalization"
    )
    original = deepcopy(client.get(finalization_url, headers=admin_headers).json())

    created = create_amendment(
        client,
        admin_headers,
        finalized_session,
    )
    assert created.status_code == 201
    amendment = created.json()
    assert amendment["status"] == "pending"
    assert amendment["sequence"] == 1
    assert amendment["payload"]["author"]["actor_role"] == "admin"
    assert amendment["payload"]["finalization_sha256"] == original["sha256"]
    assert evidence_digest(amendment["payload"]) == amendment["sha256"]

    reviewed = client.post(
        f"/api/v1/treatment-sessions/{finalized_session}/amendments/"
        f"{amendment['id']}/review",
        headers=admin_headers,
        json={"decision": "approved", "comment": "Clinically reviewed."},
    )
    assert reviewed.status_code == 201
    result = reviewed.json()
    assert result["status"] == "approved"
    assert result["review"]["payload"]["reviewer"]["actor_role"] == "admin"
    assert result["review"]["payload"]["amendment_sha256"] == amendment["sha256"]
    assert evidence_digest(result["review"]["payload"]) == result["review"]["sha256"]
    assert client.get(finalization_url, headers=admin_headers).json() == original

    events = list(
        db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_id == finalized_session,
                AuditLog.event_type.in_(
                    ["session_amendment_created", "session_amendment_approved"]
                ),
            )
            .order_by(AuditLog.created_at)
        )
    )
    assert [event.event_type for event in events] == [
        "session_amendment_created",
        "session_amendment_approved",
    ]
    assert events[0].actor_username == "testadmin"
    assert "statement" not in events[0].event_data
    assert "reason_detail" not in events[0].event_data


def test_physician_and_nurse_can_author_but_operator_and_viewer_cannot(
    client,
    admin_headers,
    finalized_session,
):
    for role in ("physician", "nurse"):
        headers = create_user_and_login(
            client,
            admin_headers,
            username=f"amendment_{role}",
            role=role,
        )
        response = create_amendment(
            client,
            headers,
            finalized_session,
            amendment_type="supplement",
            reason_code="omitted_information",
        )
        assert response.status_code == 201
        assert response.json()["payload"]["author"]["actor_role"] == role

    for role in ("operator", "viewer"):
        headers = create_user_and_login(
            client,
            admin_headers,
            username=f"amendment_{role}",
            role=role,
        )
        assert create_amendment(
            client,
            headers,
            finalized_session,
        ).status_code == 403


def test_physician_cannot_self_review_and_only_physician_or_admin_can_review(
    client,
    admin_headers,
    finalized_session,
):
    physician = create_user_and_login(
        client,
        admin_headers,
        username="amendment_physician_one",
        role="physician",
    )
    second_physician = create_user_and_login(
        client,
        admin_headers,
        username="amendment_physician_two",
        role="physician",
    )
    nurse = create_user_and_login(
        client,
        admin_headers,
        username="amendment_review_nurse",
        role="nurse",
    )
    amendment = create_amendment(
        client,
        physician,
        finalized_session,
    ).json()
    review_url = (
        f"/api/v1/treatment-sessions/{finalized_session}/amendments/"
        f"{amendment['id']}/review"
    )
    assert client.post(
        review_url,
        headers=physician,
        json={"decision": "approved"},
    ).status_code == 403
    assert client.post(
        review_url,
        headers=nurse,
        json={"decision": "approved"},
    ).status_code == 403

    approved = client.post(
        review_url,
        headers=second_physician,
        json={"decision": "approved"},
    )
    assert approved.status_code == 201
    assert approved.json()["status"] == "approved"
    assert client.post(
        review_url,
        headers=admin_headers,
        json={"decision": "rejected", "comment": "Too late."},
    ).status_code == 409


@pytest.mark.parametrize("role", ["admin", "physician", "nurse", "operator", "viewer"])
def test_all_existing_finalization_read_roles_can_read_amendments(
    client,
    admin_headers,
    finalized_session,
    role,
):
    created = create_amendment(client, admin_headers, finalized_session).json()
    headers = admin_headers
    if role != "admin":
        headers = create_user_and_login(
            client,
            admin_headers,
            username=f"amendment_reader_{role}",
            role=role,
        )
    collection_url = f"/api/v1/treatment-sessions/{finalized_session}/amendments"
    assert client.get(collection_url, headers=headers).status_code == 200
    assert client.get(
        f"{collection_url}/{created['id']}",
        headers=headers,
    ).status_code == 200
    assert client.get(collection_url).status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        amendment_json(amendment_type="rewrite"),
        amendment_json(reason_code="unspecified"),
        amendment_json(reason_detail="   "),
        amendment_json(statement=""),
        amendment_json(target_reference="  "),
        amendment_json(target_reference=None),
        {**amendment_json(), "unknown": "field"},
    ],
)
def test_invalid_amendment_payload_is_rejected(
    client,
    admin_headers,
    finalized_session,
    payload,
):
    response = client.post(
        f"/api/v1/treatment-sessions/{finalized_session}/amendments",
        headers=admin_headers,
        json=payload,
    )
    assert response.status_code == 422


def test_rejection_requires_comment_and_is_preserved(
    client,
    admin_headers,
    finalized_session,
):
    amendment = create_amendment(client, admin_headers, finalized_session).json()
    url = (
        f"/api/v1/treatment-sessions/{finalized_session}/amendments/"
        f"{amendment['id']}/review"
    )
    assert client.post(
        url,
        headers=admin_headers,
        json={"decision": "rejected"},
    ).status_code == 422
    response = client.post(
        url,
        headers=admin_headers,
        json={"decision": "rejected", "comment": "Insufficient clinical detail."},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "rejected"


def test_amendments_require_valid_captured_finalization(
    client,
    admin_headers,
    db_session,
    clinical_context,
    finalized_session,
):
    # finalized_session uses the fixture's first session; create another unfinished one.
    treatment_id = clinical_context[0]["id"]
    unfinished = client.post(
        f"/api/v1/treatments/{treatment_id}/sessions",
        headers=admin_headers,
        json={"session_number": 2},
    ).json()
    assert create_amendment(
        client,
        admin_headers,
        unfinished["id"],
    ).status_code == 404

    db_session.execute(
        update(SessionFinalization)
        .where(SessionFinalization.session_id == finalized_session)
        .values(payload={"tampered": True})
    )
    db_session.commit()
    assert create_amendment(
        client,
        admin_headers,
        finalized_session,
    ).status_code == 409


def test_sequence_is_stable_and_cross_session_lookup_is_hidden(
    client,
    admin_headers,
    db_session,
    clinical_context,
    finalized_session,
):
    first = create_amendment(client, admin_headers, finalized_session).json()
    second = create_amendment(
        client,
        admin_headers,
        finalized_session,
        amendment_type="supplement",
        reason_code="late_result",
    ).json()
    listed = client.get(
        f"/api/v1/treatment-sessions/{finalized_session}/amendments",
        headers=admin_headers,
    ).json()
    assert [item["id"] for item in listed] == [first["id"], second["id"]]
    assert [item["sequence"] for item in listed] == [1, 2]

    treatment_id = clinical_context[0]["id"]
    other = client.post(
        f"/api/v1/treatments/{treatment_id}/sessions",
        headers=admin_headers,
        json={"session_number": 2},
    ).json()
    for target in ("checked_in", "ready", "in_treatment", "completed"):
        SessionWorkflowService.transition(db_session, other["id"], target)
    response = client.get(
        f"/api/v1/treatment-sessions/{other['id']}/amendments/{first['id']}",
        headers=admin_headers,
    )
    assert response.status_code == 404


@pytest.mark.parametrize("target", ["amendment", "review"])
def test_orm_rejects_update_and_delete(
    client,
    admin_headers,
    db_session,
    finalized_session,
    target,
):
    amendment = create_amendment(client, admin_headers, finalized_session).json()
    if target == "review":
        client.post(
            f"/api/v1/treatment-sessions/{finalized_session}/amendments/"
            f"{amendment['id']}/review",
            headers=admin_headers,
            json={"decision": "approved"},
        )
        record = db_session.get(SessionAmendmentReview, amendment["id"])
        record.decision = "rejected"
    else:
        record = db_session.get(SessionAmendment, amendment["id"])
        record.payload = {"replaced": True}
    with pytest.raises(ValueError, match="cannot be updated or deleted"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(record)
    with pytest.raises(ValueError, match="cannot be updated or deleted"):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("target", ["amendment", "review"])
def test_checksum_detects_out_of_band_changes(
    client,
    admin_headers,
    db_session,
    finalized_session,
    target,
):
    amendment = create_amendment(client, admin_headers, finalized_session).json()
    if target == "review":
        client.post(
            f"/api/v1/treatment-sessions/{finalized_session}/amendments/"
            f"{amendment['id']}/review",
            headers=admin_headers,
            json={"decision": "approved"},
        )
        db_session.execute(
            update(SessionAmendmentReview)
            .where(SessionAmendmentReview.amendment_id == amendment["id"])
            .values(payload={"tampered": True})
        )
    else:
        db_session.execute(
            update(SessionAmendment)
            .where(SessionAmendment.id == amendment["id"])
            .values(payload={"tampered": True})
        )
    db_session.commit()
    response = client.get(
        f"/api/v1/treatment-sessions/{finalized_session}/amendments/{amendment['id']}",
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert "payload" not in response.json()


def test_foreign_keys_prevent_orphaning_amendment_history(
    client,
    admin_headers,
    db_session,
    finalized_session,
):
    amendment = create_amendment(client, admin_headers, finalized_session).json()
    response = client.post(
        f"/api/v1/treatment-sessions/{finalized_session}/amendments/"
        f"{amendment['id']}/review",
        headers=admin_headers,
        json={"decision": "approved"},
    )
    assert response.status_code == 201

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(SessionFinalization).where(
                SessionFinalization.session_id == finalized_session
            )
        )
        db_session.commit()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(SessionAmendment).where(
                SessionAmendment.id == amendment["id"]
            )
        )
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize("operation", ["create", "review"])
def test_amendment_write_and_audit_rollback_together(
    db_session,
    admin_headers,
    finalized_session,
    monkeypatch,
    operation,
):
    actor = db_session.scalar(select(User).where(User.username == "testadmin"))
    create_payload = SessionAmendmentCreate(**amendment_json())
    amendment = None
    if operation == "review":
        amendment = SessionAmendmentService.create(
            db_session,
            finalized_session,
            create_payload,
            actor=actor,
        )
    amendment_count = db_session.scalar(select(func.count()).select_from(SessionAmendment))
    review_count = db_session.scalar(select(func.count()).select_from(SessionAmendmentReview))
    audit_count = db_session.scalar(select(func.count()).select_from(AuditLog))
    original_audit = AuditLogRepository.create

    def fail_after_audit(*args, **kwargs):
        original_audit(*args, **kwargs)
        raise RuntimeError("injected amendment audit failure")

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_after_audit))
    with pytest.raises(RuntimeError, match="injected amendment audit failure"):
        if operation == "create":
            SessionAmendmentService.create(
                db_session,
                finalized_session,
                create_payload,
                actor=actor,
            )
        else:
            SessionAmendmentService.review(
                db_session,
                finalized_session,
                amendment.id,
                SessionAmendmentReviewCreate(decision="approved"),
                actor=actor,
            )
    assert not db_session.in_transaction()
    with Session(bind=db_session.get_bind()) as observer:
        assert observer.scalar(select(func.count()).select_from(SessionAmendment)) == amendment_count
        assert observer.scalar(select(func.count()).select_from(SessionAmendmentReview)) == review_count
        assert observer.scalar(select(func.count()).select_from(AuditLog)) == audit_count


def test_concurrent_amendments_use_parent_lock_and_stable_sequence(
    concurrent_engine,
    clinical_context,
    monkeypatch,
):
    session_id = clinical_context[2]["id"]
    with Session(concurrent_engine) as setup:
        for target in ("checked_in", "ready", "in_treatment", "completed"):
            SessionWorkflowService.transition(setup, session_id, target)

    entered = Event()
    release = Event()
    original_audit = AuditLogRepository.create

    def pause_after_audit(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        entered.set()
        assert release.wait(5), "test failed to release amendment writer"
        return result

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(pause_after_audit))

    def write_amendment(statement):
        with Session(concurrent_engine) as db:
            actor = db.scalar(select(User).where(User.username == "testadmin"))
            return SessionAmendmentService.create(
                db,
                session_id,
                SessionAmendmentCreate(
                    **amendment_json(statement=statement)
                ),
                actor=actor,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write_amendment, "First concurrent amendment.")
        try:
            assert entered.wait(5), "amendment writer did not reach audit"
            with pytest.raises(ClinicalWriteConflictError):
                write_amendment("Conflicting amendment.")
        finally:
            release.set()
        future.result(timeout=5)

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(original_audit))
    write_amendment("Second serialized amendment.")
    with Session(concurrent_engine) as observer:
        records = list(
            observer.scalars(
                select(SessionAmendment)
                .where(SessionAmendment.session_id == session_id)
                .order_by(SessionAmendment.sequence)
            )
        )
        assert [record.sequence for record in records] == [1, 2]
