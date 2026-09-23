"""Versioned controlled-pilot visit enrollment and runtime scope checks."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.pilot_release import PilotVisitEnrollmentRepository
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.pilot_release import (
    PilotVisitEnrollmentCreate,
    PilotVisitEnrollmentRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import (
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.clinical_safety_review import (
    ClinicalSafetyFindingReviewService,
)
from backend.app.services.pilot_authorization import (
    PilotReleaseDecisionIntegrityError,
    PilotReleaseDecisionNotFoundError,
    PilotReleaseDecisionService,
)
from backend.app.services.session_finalization import evidence_digest


class PilotEnrollmentNotFoundError(Exception):
    pass


class PilotEnrollmentConflictError(Exception):
    pass


class PilotEnrollmentAuthorizationError(Exception):
    pass


class PilotEnrollmentIntegrityError(Exception):
    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_timestamp(payload_value: str, column_value: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(payload_value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    return _as_utc(parsed) == _as_utc(column_value)


class PilotVisitEnrollmentService:
    @staticmethod
    def _require_physician(actor: User | None) -> User:
        if actor is None or not actor.is_active or actor.role != "physician":
            raise PilotEnrollmentAuthorizationError(
                "Only an active physician may enroll a visit into the controlled pilot."
            )
        return actor

    @staticmethod
    def _validate(record) -> dict:
        raw = deepcopy(record.payload)
        try:
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("visit_id") == record.visit_id
                and raw.get("generation") == record.generation
                and raw.get("supersedes_enrollment_id")
                == record.supersedes_enrollment_id
                and raw.get("release_decision_id") == record.release_decision_id
                and raw.get("release_decision_sha256")
                == record.release_decision_sha256
                and raw.get("clinical_context_sha256")
                == record.clinical_context_sha256
                and raw.get("protocol_template_id") == record.protocol_template_id
                and raw.get("protocol_code") == record.protocol_code
                and raw.get("protocol_version") == record.protocol_version
                and raw.get("treatment_type") == record.treatment_type
                and raw.get("rationale") == record.rationale
                and raw.get("enrolled_by_user_id") == record.enrolled_by_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("append_only") is True
                and raw.get("pilot_enrollment") is True
                and raw.get("authorizes_individual_treatment") is False
                and raw.get("requires_clinician_treatment_decision") is True
                and raw.get("is_clinical_clearance") is False
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotEnrollmentIntegrityError(
                "Stored pilot visit enrollment failed its integrity check."
            )
        return raw

    @staticmethod
    def _to_read(record) -> PilotVisitEnrollmentRead:
        PilotVisitEnrollmentService._validate(record)
        return PilotVisitEnrollmentRead(
            id=record.id,
            visit_id=record.visit_id,
            generation=record.generation,
            supersedes_enrollment_id=record.supersedes_enrollment_id,
            release_decision_id=record.release_decision_id,
            release_decision_sha256=record.release_decision_sha256,
            clinical_context_sha256=record.clinical_context_sha256,
            protocol_template_id=record.protocol_template_id,
            protocol_code=record.protocol_code,
            protocol_version=record.protocol_version,
            treatment_type=record.treatment_type,
            rationale=record.rationale,
            enrolled_by_user_id=record.enrolled_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
        )

    @staticmethod
    def _active_release_decision(db: Session, decision_id: str, expected_sha256: str):
        try:
            decision = PilotReleaseDecisionService.get(db, decision_id)
        except PilotReleaseDecisionNotFoundError as error:
            raise PilotEnrollmentNotFoundError(str(error)) from error
        except PilotReleaseDecisionIntegrityError as error:
            raise PilotEnrollmentIntegrityError(str(error)) from error

        if decision.sha256 != expected_sha256:
            raise PilotEnrollmentConflictError(
                "Pilot release decision changed; reload before enrolling."
            )
        if decision.action != "authorize":
            raise PilotEnrollmentConflictError(
                "The pilot release decision does not authorize enrollment."
            )
        now = datetime.now(timezone.utc)
        if (
            decision.starts_at is None
            or decision.expires_at is None
            or _as_utc(decision.starts_at) > now
            or _as_utc(decision.expires_at) <= now
        ):
            raise PilotEnrollmentConflictError(
                "The controlled-pilot authorization window is not active."
            )
        return decision

    @staticmethod
    def _current_context_and_safety(db: Session, visit_id: str, expected_sha256: str):
        try:
            context = ClinicalContextService.get_current_context(db, visit_id)
        except ClinicalContextNotFoundError as error:
            raise PilotEnrollmentConflictError(str(error)) from error
        except ClinicalContextIntegrityError as error:
            raise PilotEnrollmentIntegrityError(str(error)) from error
        if context.intake is None:
            raise PilotEnrollmentConflictError(
                "A final structured clinical intake is required before pilot enrollment."
            )
        context_sha256 = clinical_context_digest(context)
        if context_sha256 != expected_sha256:
            raise PilotEnrollmentConflictError(
                "Clinical context changed; reload before pilot enrollment."
            )

        inbox = ClinicalSafetyFindingReviewService.get_inbox(db, visit_id)
        if (
            inbox.current_clinical_context_sha256 != context_sha256
            or inbox.evaluation is None
            or inbox.evaluation_matches_current_context is not True
        ):
            raise PilotEnrollmentConflictError(
                "A current safety evaluation is required before pilot enrollment."
            )
        unresolved = [
            item
            for item in inbox.findings
            if item.timeline.review_status != "assessed"
        ]
        if unresolved:
            raise PilotEnrollmentConflictError(
                "All current safety findings must be physician-assessed before "
                "pilot enrollment."
            )
        return context_sha256

    @staticmethod
    @clinical_record_write
    def create(
        db: Session,
        visit_id: str,
        payload: PilotVisitEnrollmentCreate,
        *,
        actor: User | None,
    ) -> PilotVisitEnrollmentRead:
        actor = PilotVisitEnrollmentService._require_physician(actor)
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise PilotEnrollmentNotFoundError(f"Visit '{visit_id}' was not found.")

        decision = PilotVisitEnrollmentService._active_release_decision(
            db,
            payload.release_decision_id,
            payload.expected_release_decision_sha256,
        )
        context_sha256 = PilotVisitEnrollmentService._current_context_and_safety(
            db,
            visit_id,
            payload.expected_clinical_context_sha256,
        )

        protocol = ProtocolRepository.get_by_id(db, payload.protocol_template_id)
        if protocol is None:
            raise PilotEnrollmentNotFoundError(
                f"Protocol '{payload.protocol_template_id}' was not found."
            )
        if not protocol.is_active:
            raise PilotEnrollmentConflictError(
                "The selected pilot protocol is not currently active."
            )
        if protocol.code not in decision.allowed_protocol_codes:
            raise PilotEnrollmentConflictError(
                "The selected protocol is outside the human-approved pilot scope."
            )

        latest = PilotVisitEnrollmentRepository.latest_by_visit(db, visit_id)
        if latest is None:
            if (
                payload.supersedes_enrollment_id is not None
                or payload.expected_supersedes_sha256 is not None
            ):
                raise PilotEnrollmentConflictError(
                    "The first pilot enrollment cannot supersede another record."
                )
            generation = 1
            supersedes_id = None
        else:
            PilotVisitEnrollmentService._validate(latest)
            if (
                payload.supersedes_enrollment_id != latest.id
                or payload.expected_supersedes_sha256 != latest.sha256
            ):
                raise PilotEnrollmentConflictError(
                    "A new pilot enrollment must supersede the latest enrollment "
                    "and exact hash."
                )
            generation = latest.generation + 1
            supersedes_id = latest.id

        visit_already_counted = any(
            item.release_decision_id == decision.id
            for item in PilotVisitEnrollmentRepository.list_by_visit(db, visit_id)
        )
        if not visit_already_counted:
            enrolled_count = (
                PilotVisitEnrollmentRepository.count_distinct_visits_for_decision(
                    db,
                    decision.id,
                )
            )
            if (
                decision.max_enrolled_visits is None
                or enrolled_count >= decision.max_enrolled_visits
            ):
                raise PilotEnrollmentConflictError(
                    "The controlled-pilot enrollment cap has been reached."
                )

        now = datetime.now(timezone.utc)
        enrollment_id = str(uuid.uuid4())
        frozen = {
            "schema_version": 1,
            "id": enrollment_id,
            "visit_id": visit_id,
            "generation": generation,
            "supersedes_enrollment_id": supersedes_id,
            "release_decision_id": decision.id,
            "release_decision_sha256": decision.sha256,
            "clinical_context_sha256": context_sha256,
            "protocol_template_id": protocol.id,
            "protocol_code": protocol.code,
            "protocol_version": protocol.version,
            "treatment_type": protocol.treatment_type,
            "rationale": payload.rationale.strip(),
            "enrolled_by_user_id": actor.id,
            "created_at": now.isoformat(),
            "append_only": True,
            "pilot_enrollment": True,
            "authorizes_individual_treatment": False,
            "requires_clinician_treatment_decision": True,
            "is_clinical_clearance": False,
        }
        sha256 = evidence_digest(frozen)
        record = PilotVisitEnrollmentRepository.create(
            db,
            enrollment_id=enrollment_id,
            visit_id=visit_id,
            generation=generation,
            supersedes_enrollment_id=supersedes_id,
            release_decision_id=decision.id,
            release_decision_sha256=decision.sha256,
            clinical_context_sha256=context_sha256,
            protocol_template_id=protocol.id,
            protocol_code=protocol.code,
            protocol_version=protocol.version,
            treatment_type=protocol.treatment_type,
            rationale=payload.rationale.strip(),
            enrolled_by_user_id=actor.id,
            payload=frozen,
            sha256=sha256,
            created_at=now,
        )
        AuditLogRepository.create(
            db,
            entity_type="pilot_visit_enrollment",
            entity_id=record.id,
            event_type="pilot_visit_enrolled",
            from_state=None,
            to_state="enrolled",
            event_data={
                "visit_id": visit_id,
                "generation": generation,
                "release_decision_id": decision.id,
                "release_decision_sha256": decision.sha256,
                "clinical_context_sha256": context_sha256,
                "protocol_template_id": protocol.id,
                "protocol_code": protocol.code,
                "protocol_version": protocol.version,
                "enrollment_sha256": sha256,
            },
            commit=False,
            **actor_data(actor),
        )
        return PilotVisitEnrollmentService._to_read(record)

    @staticmethod
    def get_latest(
        db: Session,
        visit_id: str,
    ) -> PilotVisitEnrollmentRead | None:
        record = PilotVisitEnrollmentRepository.latest_by_visit(db, visit_id)
        return (
            PilotVisitEnrollmentService._to_read(record)
            if record is not None
            else None
        )

    @staticmethod
    def list_by_visit(
        db: Session,
        visit_id: str,
    ) -> list[PilotVisitEnrollmentRead]:
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise PilotEnrollmentNotFoundError(f"Visit '{visit_id}' was not found.")
        return [
            PilotVisitEnrollmentService._to_read(item)
            for item in PilotVisitEnrollmentRepository.list_by_visit(db, visit_id)
        ]

    @staticmethod
    def list(db: Session) -> list[PilotVisitEnrollmentRead]:
        return [
            PilotVisitEnrollmentService._to_read(item)
            for item in PilotVisitEnrollmentRepository.list(db)
        ]

    @staticmethod
    def validate_runtime_scope(
        db: Session,
        visit_id: str,
        protocol_template_id: str | None,
    ) -> PilotVisitEnrollmentRead | None:
        record = PilotVisitEnrollmentRepository.latest_by_visit(db, visit_id)
        if record is None:
            return None
        enrollment = PilotVisitEnrollmentService._to_read(record)

        decision = PilotVisitEnrollmentService._active_release_decision(
            db,
            enrollment.release_decision_id,
            enrollment.release_decision_sha256,
        )
        if protocol_template_id is None or protocol_template_id != enrollment.protocol_template_id:
            raise PilotEnrollmentConflictError(
                "An enrolled pilot visit must use the exact protocol version "
                "frozen at enrollment."
            )
        protocol = ProtocolRepository.get_by_id(db, enrollment.protocol_template_id)
        if (
            protocol is None
            or not protocol.is_active
            or protocol.code not in decision.allowed_protocol_codes
            or protocol.code != enrollment.protocol_code
            or protocol.version != enrollment.protocol_version
        ):
            raise PilotEnrollmentConflictError(
                "The enrolled pilot protocol is no longer valid within the "
                "active release scope."
            )
        PilotVisitEnrollmentService._current_context_and_safety(
            db,
            visit_id,
            enrollment.clinical_context_sha256,
        )
        return enrollment
