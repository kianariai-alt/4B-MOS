"""Visit-serialized writes, explicit retries, and independent consent purposes."""

from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.reception import ReceptionRevision, VisitConsentEvent
from backend.app.models.visit import Visit
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.reception import (
    CONSENT_PURPOSES,
    ConsentCreate,
    ConsentState,
    EvidenceRead,
    ReceptionCreate,
    ReceptionWorkspace,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.session_finalization import evidence_digest


class ReceptionNotFoundError(Exception):
    pass


class ReceptionConflictError(Exception):
    pass


class ReceptionAuthorizationError(Exception):
    pass


def _visit(db, visit_id):
    visit = db.get(Visit, visit_id)
    if visit is None:
        raise ReceptionNotFoundError("Visit not found.")
    return visit


def _authorize(actor):
    if not actor.is_active or actor.role not in {"admin", "operator", "physician"}:
        raise ReceptionAuthorizationError("Reception write access required.")


def _read(row):
    p = row.payload
    if (
        not isinstance(p, dict)
        or evidence_digest(p) != row.sha256
        or p.get("id") != row.id
        or p.get("visit_id") != row.visit_id
        or p.get("version") != row.version
        or p.get("request_key") != row.request_key
        or p.get("recorded_by") != row.recorded_by
        or p.get("created_at")
        != row.created_at.replace(tzinfo=timezone.utc).isoformat()
    ):
        raise ReceptionConflictError("Reception evidence integrity check failed.")
    return EvidenceRead(
        **{
            k: p[k]
            for k in (
                "id",
                "visit_id",
                "version",
                "request_key",
                "recorded_by",
                "created_at",
            )
        },
        sha256=row.sha256,
        content=p["command"]
    )


def _rows(db, model, visit_id):
    rows = list(
        db.scalars(
            select(model).where(model.visit_id == visit_id).order_by(model.version)
        )
    )
    for version, row in enumerate(rows, start=1):
        _read(row)
        if row.version != version:
            raise ReceptionConflictError("Reception evidence sequence is incomplete.")
    return rows


def _record(db, model, visit_id, command, actor, rows):
    data = command.model_dump(mode="json")
    for row in rows:
        if row.request_key == command.request_key:
            if row.payload["command"] != data or row.recorded_by != actor.id:
                raise ReceptionConflictError(
                    "Request key was already used for a different command."
                )
            return _read(row)
    if command.expected_version != len(rows):
        raise ReceptionConflictError("Version changed; reload before submitting.")
    now = datetime.now(timezone.utc)
    identifier = str(uuid.uuid4())
    payload = {
        "schema_version": 1,
        "id": identifier,
        "visit_id": visit_id,
        "version": len(rows) + 1,
        "request_key": command.request_key,
        "recorded_by": actor.id,
        "created_at": now.isoformat(),
        "command": data,
    }
    row = model(
        id=identifier,
        visit_id=visit_id,
        version=len(rows) + 1,
        request_key=command.request_key,
        recorded_by=actor.id,
        created_at=now,
        payload=payload,
        sha256=evidence_digest(payload),
    )
    db.add(row)
    db.flush()
    # Audit stores identifiers and hashes, never patient contact or free text.
    AuditLogRepository.create(
        db,
        entity_type=model.__tablename__,
        entity_id=row.id,
        event_type="created",
        event_data={"visit_id": visit_id, "version": row.version, "sha256": row.sha256},
        **actor_data(actor),
        commit=False
    )
    return _read(row)


class ReceptionService:
    @staticmethod
    @clinical_record_write
    def save_intake(
        db: Session, visit_id: str, payload: ReceptionCreate, *, actor: User
    ):
        _authorize(actor)
        visit = _visit(db, visit_id)
        rows = _rows(db, ReceptionRevision, visit_id)
        # Permit an exact retry even when the visit subsequently closed.
        if not any(r.request_key == payload.request_key for r in rows):
            if visit.status != "open":
                raise ReceptionConflictError(
                    "New reception revisions require an open visit."
                )
            if payload.assigned_physician_id:
                physician = db.get(User, payload.assigned_physician_id)
                if (
                    physician is None
                    or not physician.is_active
                    or physician.role != "physician"
                ):
                    raise ReceptionConflictError(
                        "Assigned physician must be an active physician."
                    )
        return _record(db, ReceptionRevision, visit_id, payload, actor, rows)

    @staticmethod
    @clinical_record_write
    def record_consent(
        db: Session, visit_id: str, payload: ConsentCreate, *, actor: User
    ):
        _authorize(actor)
        _visit(db, visit_id)
        # Consent withdrawal remains available after a visit closes.
        return _record(
            db,
            VisitConsentEvent,
            visit_id,
            payload,
            actor,
            _rows(db, VisitConsentEvent, visit_id),
        )

    @staticmethod
    def workspace(db: Session, visit_id: str):
        visit = _visit(db, visit_id)
        intakes = _rows(db, ReceptionRevision, visit_id)
        events = _rows(db, VisitConsentEvent, visit_id)
        latest = {r.payload["command"]["purpose"]: _read(r) for r in events}
        return ReceptionWorkspace(
            visit_id=visit_id,
            patient_id=visit.patient_id,
            latest_intake=_read(intakes[-1]) if intakes else None,
            intake_version=len(intakes),
            consent_version=len(events),
            consents=[
                ConsentState(
                    purpose=p,
                    state=latest[p].content["state"] if p in latest else "unknown",
                    latest_event=latest.get(p),
                )
                for p in CONSENT_PURPOSES
            ],
        )

    @staticmethod
    def history(db: Session, visit_id: str, *, consent: bool = False):
        _visit(db, visit_id)
        return [
            _read(r)
            for r in _rows(
                db, VisitConsentEvent if consent else ReceptionRevision, visit_id
            )
        ]

    @staticmethod
    def consent_granted(db: Session, visit_id: str, purpose: str) -> bool:
        if purpose not in CONSENT_PURPOSES:
            raise ValueError("Unknown consent purpose.")
        workspace = ReceptionService.workspace(db, visit_id)
        return next(
            c.state == "granted" for c in workspace.consents if c.purpose == purpose
        )
