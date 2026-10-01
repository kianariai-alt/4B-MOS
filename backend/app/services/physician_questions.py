"""Versioned physician-owned drafts and explicit hash-bound approval."""
from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from backend.app.db.account_transactions import atomic_account_write
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services.audit_context import actor_data
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.reception import ReceptionService
from backend.app.schemas.physician_questions import BankEventRead, BankWorkspaceRead, VisitQuestionBankRead

class QuestionBankNotFoundError(Exception): pass
class QuestionBankAuthorizationError(Exception): pass
class QuestionBankConflictError(Exception): pass

def _authorize(db, physician_id, actor, write=False):
    physician = db.get(User, physician_id)
    if physician is None or not physician.is_active or physician.role != "physician":
        raise QuestionBankNotFoundError("Active physician not found.")
    current = db.get(User, actor.id)
    if current is None or not current.is_active or not ((current.role == "physician" and current.id == physician_id) or (not write and current.role == "admin")):
        raise QuestionBankAuthorizationError("Only the owning physician can change or approve this bank.")

def _read(row):
    p = row.payload
    if not isinstance(p, dict) or evidence_digest(p) != row.sha256 or any(p.get(k) != getattr(row,k) for k in ("id", "physician_id", "version", "action", "request_key", "recorded_by")) or p.get("created_at") != row.created_at.replace(tzinfo=timezone.utc).isoformat():
        raise QuestionBankConflictError("Question bank integrity check failed.")
    return BankEventRead(**p, sha256=row.sha256)

def _rows(db, physician_id):
    rows = list(db.scalars(select(PhysicianQuestionEvent).where(PhysicianQuestionEvent.physician_id == physician_id).order_by(PhysicianQuestionEvent.version)))
    for version, row in enumerate(rows, 1):
        _read(row)
        if version != row.version:
            raise QuestionBankConflictError("Question bank history is incomplete.")
    return rows

def _active(rows):
    active = None
    for row in rows:
        if row.action == "approve": active = row
        elif row.action == "retire": active = None
    return active

def _retry(rows, payload, actor, action):
    for row in rows:
        if row.request_key == payload.request_key:
            if row.action != action or row.recorded_by != actor.id or row.payload["command"] != payload.model_dump(mode="json"):
                raise QuestionBankConflictError("Request key already used for a different command.")
            return _read(row)
    if payload.expected_version != len(rows):
        raise QuestionBankConflictError("Version changed; reload before submitting.")
    return None

def _append(db, physician_id, rows, payload, actor, action, content, reviewed=None):
    now = datetime.now(timezone.utc)
    body = dict(schema_version=1, id=str(uuid.uuid4()), physician_id=physician_id, version=len(rows)+1, action=action, request_key=payload.request_key, recorded_by=actor.id, created_at=now.isoformat(), command=payload.model_dump(mode="json"), content=content, reviewed_bank_sha256=reviewed)
    row = PhysicianQuestionEvent(**{k:body[k] for k in ("id", "physician_id", "version", "action", "request_key", "recorded_by")}, created_at=now, payload=body, sha256=evidence_digest(body))
    db.add(row)
    db.flush()
    AuditLogRepository.create(db, entity_type=row.__tablename__, entity_id=row.id, event_type=action, event_data={"physician_id":physician_id,"version":row.version,"sha256":row.sha256}, **actor_data(actor), commit=False)
    return _read(row)

class PhysicianQuestionService:
    @staticmethod
    def workspace(db, physician_id, *, actor):
        _authorize(db, physician_id, actor)
        rows = _rows(db, physician_id)
        active = _active(rows)
        return BankWorkspaceRead(physician_id=physician_id, version=len(rows), latest=_read(rows[-1]) if rows else None, active_bank=_read(active) if active else None, has_approved_bank=active is not None)

    @staticmethod
    @atomic_account_write
    def save_draft(db, physician_id, payload, *, actor):
        _authorize(db, physician_id, actor, write=True)
        rows = _rows(db, physician_id)
        retry = _retry(rows, payload, actor, "draft")
        if retry: return retry
        content = payload.model_dump(mode="json", exclude={"request_key", "expected_version"})
        return _append(db, physician_id, rows, payload, actor, "draft", content)

    @staticmethod
    @atomic_account_write
    def review(db, physician_id, payload, *, actor, action):
        if action not in {"approve", "retire"}: raise ValueError("Unknown review action.")
        _authorize(db, physician_id, actor, write=True)
        rows = _rows(db, physician_id)
        retry = _retry(rows, payload, actor, action)
        if retry: return retry
        target = rows[-1] if rows and action == "approve" else _active(rows)
        if target is None or (action == "approve" and target.action != "draft") or target.sha256 != payload.expected_bank_sha256:
            raise QuestionBankConflictError("Review requires the exact current draft or approved bank hash.")
        return _append(db, physician_id, rows, payload, actor, action, target.payload["content"], target.sha256)

    @staticmethod
    def approved_questions_for_visit(db, visit_id, *, actor):
        current = db.get(User, actor.id)
        if current is None or not current.is_active or current.role not in {"admin", "operator", "physician", "nurse"}:
            raise QuestionBankAuthorizationError("Screening read access required.")
        workspace = ReceptionService.workspace(db, visit_id)
        physician_id = workspace.latest_intake.content.get("assigned_physician_id") if workspace.latest_intake else None
        result = VisitQuestionBankRead(visit_id=visit_id, physician_id=physician_id)
        physician = db.get(User, physician_id) if physician_id else None
        if physician is None or not physician.is_active or physician.role != "physician": return result
        active = _active(_rows(db, physician_id))
        if active:
            result.bank_id = active.id
            result.bank_sha256 = active.sha256
            result.questions = _read(active).content.questions
            result.has_approved_bank = True
        return result
