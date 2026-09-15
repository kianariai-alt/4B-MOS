"""Append-only clinical amendments linked to immutable finalization evidence."""

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.transactions import atomic_write
from backend.app.models.session_amendment import (
    SessionAmendment,
    SessionAmendmentReview,
)
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.session_amendment import SessionAmendmentRepository
from backend.app.schemas.session_amendment import (
    SessionAmendmentCreate,
    SessionAmendmentPayloadRead,
    SessionAmendmentRead,
    SessionAmendmentReviewCreate,
    SessionAmendmentReviewPayloadRead,
    SessionAmendmentReviewRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.session_finalization import (
    SessionFinalizationService,
    evidence_digest,
)


AMENDMENT_AUTHOR_ROLES = {"admin", "physician", "nurse"}
AMENDMENT_REVIEW_ROLES = {"admin", "physician"}


class SessionAmendmentNotFoundError(Exception):
    pass


class SessionAmendmentConflictError(Exception):
    pass


class SessionAmendmentAuthorizationError(Exception):
    pass


class SessionAmendmentIntegrityError(Exception):
    pass


def _same_timestamp(payload_value: str, column_value: datetime) -> bool:
    try:
        payload_value = datetime.fromisoformat(payload_value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if payload_value.tzinfo is None:
        payload_value = payload_value.replace(tzinfo=timezone.utc)
    else:
        payload_value = payload_value.astimezone(timezone.utc)
    if column_value.tzinfo is None:
        column_value = column_value.replace(tzinfo=timezone.utc)
    else:
        column_value = column_value.astimezone(timezone.utc)
    return payload_value == column_value


class SessionAmendmentService:
    @staticmethod
    def _require_actor(actor: User | None, allowed_roles: set[str]) -> User:
        if actor is None or not actor.is_active or actor.role not in allowed_roles:
            raise SessionAmendmentAuthorizationError(
                "The current role is not allowed to perform this amendment action."
            )
        return actor

    @staticmethod
    def _validate_amendment(
        record: SessionAmendment,
        *,
        finalization_sha256: str,
    ) -> SessionAmendmentPayloadRead:
        try:
            raw = record.payload
            payload = SessionAmendmentPayloadRead.model_validate(deepcopy(raw))
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and payload.id == record.id
                and payload.session_id == record.session_id
                and payload.sequence == record.sequence
                and payload.finalization_sha256 == finalization_sha256
                and _same_timestamp(payload.created_at, record.created_at)
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            valid = False
            payload = None
        if not valid or payload is None:
            raise SessionAmendmentIntegrityError(
                "Stored session amendment failed its integrity check."
            )
        return payload

    @staticmethod
    def _validate_review(
        review: SessionAmendmentReview,
        *,
        amendment: SessionAmendment,
    ) -> SessionAmendmentReviewPayloadRead:
        try:
            raw = review.payload
            payload = SessionAmendmentReviewPayloadRead.model_validate(deepcopy(raw))
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == review.sha256
                and payload.amendment_id == review.amendment_id == amendment.id
                and payload.session_id == amendment.session_id
                and payload.amendment_sha256 == amendment.sha256
                and payload.decision == review.decision
                and _same_timestamp(payload.reviewed_at, review.reviewed_at)
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            valid = False
            payload = None
        if not valid or payload is None:
            raise SessionAmendmentIntegrityError(
                "Stored session amendment review failed its integrity check."
            )
        return payload

    @staticmethod
    def _to_read(
        db: Session,
        record: SessionAmendment,
        *,
        finalization_sha256: str,
    ) -> SessionAmendmentRead:
        payload = SessionAmendmentService._validate_amendment(
            record,
            finalization_sha256=finalization_sha256,
        )
        stored_review = SessionAmendmentRepository.get_review(db, record.id)
        review_read = None
        status = "pending"
        if stored_review is not None:
            review_payload = SessionAmendmentService._validate_review(
                stored_review,
                amendment=record,
            )
            status = stored_review.decision
            review_read = SessionAmendmentReviewRead(
                amendment_id=stored_review.amendment_id,
                decision=stored_review.decision,
                reviewed_at=stored_review.reviewed_at,
                sha256=stored_review.sha256,
                payload=review_payload,
            )
        return SessionAmendmentRead(
            id=record.id,
            session_id=record.session_id,
            sequence=record.sequence,
            status=status,
            created_at=record.created_at,
            sha256=record.sha256,
            payload=payload,
            review=review_read,
        )

    @staticmethod
    @atomic_write
    def create(
        db: Session,
        session_id: str,
        payload: SessionAmendmentCreate,
        actor: User | None = None,
    ) -> SessionAmendmentRead:
        actor = SessionAmendmentService._require_actor(
            actor,
            AMENDMENT_AUTHOR_ROLES,
        )
        finalization = SessionFinalizationService.get(db, session_id)
        amendment_id = str(uuid.uuid4())
        sequence = SessionAmendmentRepository.next_sequence(db, session_id)
        created_at = datetime.now(timezone.utc)
        stored_payload = {
            "schema_version": 1,
            "id": amendment_id,
            "session_id": session_id,
            "sequence": sequence,
            "finalization_sha256": finalization.sha256,
            "amendment_type": payload.amendment_type,
            "reason_code": payload.reason_code,
            "reason_detail": payload.reason_detail,
            "statement": payload.statement,
            "target_reference": payload.target_reference,
            "author": actor_data(actor),
            "created_at": created_at.isoformat(),
        }
        sha256 = evidence_digest(stored_payload)
        try:
            record = SessionAmendmentRepository.create(
                db,
                amendment_id=amendment_id,
                session_id=session_id,
                sequence=sequence,
                created_at=created_at,
                payload=stored_payload,
                sha256=sha256,
            )
        except IntegrityError as exc:
            raise SessionAmendmentConflictError(
                "The amendment conflicts with another write; reload before retrying."
            ) from exc

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="treatment_session",
            entity_id=session_id,
            event_type="session_amendment_created",
            message="An append-only session amendment was recorded for review.",
            event_data={
                "amendment_id": amendment_id,
                "sequence": sequence,
                "amendment_type": payload.amendment_type,
                "reason_code": payload.reason_code,
                "finalization_sha256": finalization.sha256,
                "amendment_sha256": sha256,
            },
            **actor_data(actor),
        )
        return SessionAmendmentService._to_read(
            db,
            record,
            finalization_sha256=finalization.sha256,
        )

    @staticmethod
    def list_for_session(db: Session, session_id: str) -> list[SessionAmendmentRead]:
        finalization = SessionFinalizationService.get(db, session_id)
        return [
            SessionAmendmentService._to_read(
                db,
                record,
                finalization_sha256=finalization.sha256,
            )
            for record in SessionAmendmentRepository.list_by_session(db, session_id)
        ]

    @staticmethod
    def get(
        db: Session,
        session_id: str,
        amendment_id: str,
    ) -> SessionAmendmentRead:
        finalization = SessionFinalizationService.get(db, session_id)
        record = SessionAmendmentRepository.get_by_id(db, amendment_id)
        if record is None or record.session_id != session_id:
            raise SessionAmendmentNotFoundError(
                f"Session amendment '{amendment_id}' was not found for this session."
            )
        return SessionAmendmentService._to_read(
            db,
            record,
            finalization_sha256=finalization.sha256,
        )

    @staticmethod
    @atomic_write
    def review(
        db: Session,
        session_id: str,
        amendment_id: str,
        payload: SessionAmendmentReviewCreate,
        actor: User | None = None,
    ) -> SessionAmendmentRead:
        actor = SessionAmendmentService._require_actor(
            actor,
            AMENDMENT_REVIEW_ROLES,
        )
        finalization = SessionFinalizationService.get(db, session_id)
        record = SessionAmendmentRepository.get_by_id(db, amendment_id)
        if record is None or record.session_id != session_id:
            raise SessionAmendmentNotFoundError(
                f"Session amendment '{amendment_id}' was not found for this session."
            )
        amendment_payload = SessionAmendmentService._validate_amendment(
            record,
            finalization_sha256=finalization.sha256,
        )
        if SessionAmendmentRepository.get_review(db, amendment_id) is not None:
            raise SessionAmendmentConflictError(
                "This session amendment already has a final review decision."
            )
        if (
            amendment_payload.author.actor_user_id == actor.id
            and actor.role != "admin"
        ):
            raise SessionAmendmentAuthorizationError(
                "Only an administrator may approve or reject their own amendment."
            )

        reviewed_at = datetime.now(timezone.utc)
        stored_payload = {
            "schema_version": 1,
            "amendment_id": amendment_id,
            "session_id": session_id,
            "amendment_sha256": record.sha256,
            "decision": payload.decision,
            "comment": payload.comment,
            "reviewer": actor_data(actor),
            "reviewed_at": reviewed_at.isoformat(),
        }
        review_sha256 = evidence_digest(stored_payload)
        try:
            SessionAmendmentRepository.create_review(
                db,
                amendment_id=amendment_id,
                decision=payload.decision,
                reviewed_at=reviewed_at,
                payload=stored_payload,
                sha256=review_sha256,
            )
        except IntegrityError as exc:
            raise SessionAmendmentConflictError(
                "This session amendment already has a final review decision."
            ) from exc

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="treatment_session",
            entity_id=session_id,
            event_type=f"session_amendment_{payload.decision}",
            message=f"Session amendment review recorded as '{payload.decision}'.",
            event_data={
                "amendment_id": amendment_id,
                "sequence": record.sequence,
                "amendment_sha256": record.sha256,
                "review_sha256": review_sha256,
                "decision": payload.decision,
            },
            **actor_data(actor),
        )
        return SessionAmendmentService._to_read(
            db,
            record,
            finalization_sha256=finalization.sha256,
        )
