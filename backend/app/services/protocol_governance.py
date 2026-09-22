"""Human-governed protocol learning workflow.

The system surfaces data-quality signals and preserves governance review
provenance. It never applies a protocol change automatically.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.protocol_governance import ProtocolGovernanceRepository
from backend.app.schemas.protocol import ProtocolRead
from backend.app.schemas.protocol_governance import (
    ProtocolGovernanceCaseCreate,
    ProtocolGovernanceCaseRead,
    ProtocolGovernanceReviewCreate,
    ProtocolGovernanceReviewRead,
    ProtocolGovernanceSignalRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_learning_review import (
    ClinicalLearningIntegrityError,
    ClinicalLearningReviewService,
)
from backend.app.services.session_finalization import evidence_digest


class ProtocolGovernanceNotFoundError(Exception):
    pass


class ProtocolGovernanceConflictError(Exception):
    pass


class ProtocolGovernanceAuthorizationError(Exception):
    pass


class ProtocolGovernanceIntegrityError(Exception):
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


class ProtocolGovernanceService:
    @staticmethod
    def list_signals(db: Session) -> list[ProtocolGovernanceSignalRead]:
        try:
            learning = ClinicalLearningReviewService.get_review(db)
        except ClinicalLearningIntegrityError as error:
            raise ProtocolGovernanceIntegrityError(str(error)) from error

        signals = []
        for item in learning.protocols:
            current = []
            if item.data_volume == "insufficient":
                current.append("insufficient_outcome_volume")
            elif item.data_volume in {"very_limited", "limited"}:
                current.append("limited_outcome_volume")
            for flag in item.data_quality_flags:
                if flag == "no_decision_linked_treatments":
                    current.append("no_decision_linked_treatments")
                elif flag in {
                    "patient_rating_incomplete",
                    "physician_rating_incomplete",
                    "pain_score_incomplete",
                    "function_score_incomplete",
                }:
                    current.append(flag)
            if item.follow_up_counts.early_28_to_70_days == 0:
                current.append("early_followup_gap")
            if item.follow_up_counts.intermediate_71_to_180_days == 0:
                current.append("intermediate_followup_gap")
            if item.follow_up_counts.long_term_181_to_365_days == 0:
                current.append("long_term_followup_gap")
            if (
                item.data_volume in {"moderate", "substantial"}
                and not item.data_quality_flags
                and (
                    item.follow_up_counts.early_28_to_70_days
                    + item.follow_up_counts.intermediate_71_to_180_days
                    + item.follow_up_counts.long_term_181_to_365_days
                ) > 0
            ):
                current.append("eligible_for_human_pattern_review")

            signals.append(
                ProtocolGovernanceSignalRead(
                    protocol_code=item.protocol_code,
                    protocol_version=item.protocol_version,
                    protocol_name=item.protocol_name,
                    treatment_type=item.treatment_type,
                    is_active=item.is_active,
                    data_volume=item.data_volume,
                    signals=current,
                    source_learning_review_sha256=learning.review_sha256,
                )
            )
        return signals

    @staticmethod
    def _case_status(reviews: list) -> str:
        latest_clinical = None
        latest_operational = None
        for review in reviews:
            if review.action in {
                "clinical_approve",
                "clinical_reject",
                "request_changes",
            }:
                latest_clinical = review
            elif review.action in {
                "operational_acknowledge",
                "operational_hold",
            }:
                latest_operational = review

        if latest_clinical is None:
            return "awaiting_clinical_review"
        if latest_clinical.action == "request_changes":
            return "changes_requested"
        if latest_clinical.action == "clinical_reject":
            return "clinically_rejected"
        if latest_operational is None:
            return "awaiting_operational_review"
        if latest_operational.action == "operational_hold":
            return "operational_hold"
        return "approved_for_manual_action"

    @staticmethod
    def _validate_case_record(db: Session, record):
        try:
            raw = deepcopy(record.payload)
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("protocol_code") == record.protocol_code
                and raw.get("protocol_version") == record.protocol_version
                and raw.get("treatment_type") == record.treatment_type
                and raw.get("case_type") == record.case_type
                and raw.get("source_learning_review_sha256")
                == record.source_learning_review_sha256
                and raw.get("protocol_snapshot") == record.protocol_snapshot
                and raw.get("learning_snapshot") == record.learning_snapshot
                and raw.get("proposed_protocol") == record.proposed_protocol
                and raw.get("rationale") == record.rationale
                and raw.get("evidence_needed") == list(record.evidence_needed)
                and raw.get("created_by_user_id") == record.created_by_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("automatically_changes_protocol") is False
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ProtocolGovernanceIntegrityError(
                "Stored protocol governance case failed its integrity check."
            )
        return raw

    @staticmethod
    def _validate_review_record(record, case_sha256: str):
        try:
            raw = deepcopy(record.payload)
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("case_id") == record.case_id
                and raw.get("case_sha256") == record.case_sha256 == case_sha256
                and raw.get("action") == record.action
                and raw.get("rationale") == record.rationale
                and raw.get("reviewer_user_id") == record.reviewer_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ProtocolGovernanceIntegrityError(
                "Stored protocol governance review failed its integrity check."
            )
        return raw

    @staticmethod
    def _to_read(db: Session, record) -> ProtocolGovernanceCaseRead:
        ProtocolGovernanceService._validate_case_record(db, record)
        reviews = ProtocolGovernanceRepository.list_reviews(db, record.id)
        review_reads = []
        for review in reviews:
            ProtocolGovernanceService._validate_review_record(
                review,
                record.sha256,
            )
            review_reads.append(
                ProtocolGovernanceReviewRead(
                    id=review.id,
                    case_id=review.case_id,
                    case_sha256=review.case_sha256,
                    action=review.action,
                    rationale=review.rationale,
                    reviewer_user_id=review.reviewer_user_id,
                    sha256=review.sha256,
                    created_at=review.created_at,
                )
            )
        return ProtocolGovernanceCaseRead(
            id=record.id,
            protocol_code=record.protocol_code,
            protocol_version=record.protocol_version,
            treatment_type=record.treatment_type,
            case_type=record.case_type,
            source_learning_review_sha256=record.source_learning_review_sha256,
            protocol_snapshot=deepcopy(record.protocol_snapshot),
            learning_snapshot=deepcopy(record.learning_snapshot),
            proposed_protocol=deepcopy(record.proposed_protocol),
            rationale=record.rationale,
            evidence_needed=list(record.evidence_needed),
            created_by_user_id=record.created_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
            reviews=review_reads,
            status=ProtocolGovernanceService._case_status(review_reads),
        )

    @staticmethod
    def create_case(
        db: Session,
        payload: ProtocolGovernanceCaseCreate,
        *,
        actor: User | None,
    ) -> ProtocolGovernanceCaseRead:
        if actor is None or not actor.is_active or actor.role != "physician":
            raise ProtocolGovernanceAuthorizationError(
                "Only an active physician may open a protocol governance case."
            )
        try:
            learning = ClinicalLearningReviewService.get_review(db)
        except ClinicalLearningIntegrityError as error:
            raise ProtocolGovernanceIntegrityError(str(error)) from error

        if payload.source_learning_review_sha256 != learning.review_sha256:
            raise ProtocolGovernanceConflictError(
                "The clinical learning review changed; reload it before "
                "opening a governance case."
            )
        source = next(
            (
                item for item in learning.protocols
                if item.protocol_code == payload.protocol_code
                and item.protocol_version == payload.protocol_version
            ),
            None,
        )
        if source is None:
            raise ProtocolGovernanceNotFoundError(
                "The requested protocol version is not present in the current "
                "clinical learning review."
            )
        protocol = ProtocolRepository.get_by_code_version(
            db,
            payload.protocol_code,
            payload.protocol_version,
        )
        if protocol is None:
            raise ProtocolGovernanceNotFoundError(
                "The protocol version is missing from the protocol registry."
            )

        proposed = (
            payload.proposed_protocol.model_dump(mode="json")
            if payload.proposed_protocol is not None
            else None
        )
        if payload.case_type == "revision_candidate":
            candidate = payload.proposed_protocol
            assert candidate is not None
            if (
                candidate.code != protocol.code
                or candidate.treatment_type != protocol.treatment_type
            ):
                raise ProtocolGovernanceConflictError(
                    "A revision candidate must preserve the protocol code and "
                    "treatment type."
                )
            if candidate.version == protocol.version:
                raise ProtocolGovernanceConflictError(
                    "A revision candidate must use a new protocol version."
                )
            if ProtocolRepository.get_by_code_version(
                db,
                candidate.code,
                candidate.version,
            ) is not None:
                raise ProtocolGovernanceConflictError(
                    "The proposed protocol version already exists."
                )
        if (
            payload.case_type == "deactivation_candidate"
            and not protocol.is_active
        ):
            raise ProtocolGovernanceConflictError(
                "An inactive protocol cannot be proposed for deactivation."
            )

        case_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        protocol_snapshot = ProtocolRead.model_validate(protocol).model_dump(
            mode="json"
        )
        learning_snapshot = source.model_dump(mode="json")
        stored = {
            "schema_version": 1,
            "id": case_id,
            "protocol_code": protocol.code,
            "protocol_version": protocol.version,
            "treatment_type": protocol.treatment_type,
            "case_type": payload.case_type,
            "source_learning_review_sha256": learning.review_sha256,
            "protocol_snapshot": protocol_snapshot,
            "learning_snapshot": learning_snapshot,
            "proposed_protocol": proposed,
            "rationale": payload.rationale,
            "evidence_needed": list(payload.evidence_needed),
            "created_by_user_id": actor.id,
            "created_at": created_at.isoformat(),
            "automatically_changes_protocol": False,
        }
        sha256 = evidence_digest(stored)
        try:
            record = ProtocolGovernanceRepository.create_case(
                db,
                id=case_id,
                protocol_code=protocol.code,
                protocol_version=protocol.version,
                treatment_type=protocol.treatment_type,
                case_type=payload.case_type,
                source_learning_review_sha256=learning.review_sha256,
                protocol_snapshot=protocol_snapshot,
                learning_snapshot=learning_snapshot,
                proposed_protocol=proposed,
                rationale=payload.rationale,
                evidence_needed=list(payload.evidence_needed),
                created_by_user_id=actor.id,
                payload=stored,
                sha256=sha256,
                created_at=created_at,
            )
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="protocol_governance_case",
                entity_id=record.id,
                event_type="protocol_governance_case_opened",
                from_state=None,
                to_state="awaiting_clinical_review",
                message="A physician opened an immutable protocol governance case.",
                event_data={
                    "protocol_code": protocol.code,
                    "protocol_version": protocol.version,
                    "case_type": payload.case_type,
                    "source_learning_review_sha256": learning.review_sha256,
                    "case_sha256": sha256,
                    "automatically_changes_protocol": False,
                },
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ProtocolGovernanceConflictError(
                "The governance case conflicted with another write."
            ) from error
        return ProtocolGovernanceService._to_read(db, record)

    @staticmethod
    def add_review(
        db: Session,
        case_id: str,
        payload: ProtocolGovernanceReviewCreate,
        *,
        actor: User | None,
    ) -> ProtocolGovernanceCaseRead:
        record = ProtocolGovernanceRepository.get_case(db, case_id)
        if record is None:
            raise ProtocolGovernanceNotFoundError(
                f"Protocol governance case '{case_id}' was not found."
            )
        ProtocolGovernanceService._validate_case_record(db, record)
        if payload.expected_case_sha256 != record.sha256:
            raise ProtocolGovernanceConflictError(
                "The governance case hash changed; reload before reviewing."
            )
        if actor is None or not actor.is_active:
            raise ProtocolGovernanceAuthorizationError(
                "An active authenticated reviewer is required."
            )

        clinical_actions = {
            "clinical_approve",
            "clinical_reject",
            "request_changes",
        }
        operational_actions = {
            "operational_acknowledge",
            "operational_hold",
        }
        existing = ProtocolGovernanceRepository.list_reviews(db, case_id)
        for item in existing:
            ProtocolGovernanceService._validate_review_record(
                item,
                record.sha256,
            )

        if payload.action in clinical_actions:
            if actor.role != "physician":
                raise ProtocolGovernanceAuthorizationError(
                    "Only a physician may perform clinical governance review."
                )
            if actor.id == record.created_by_user_id:
                raise ProtocolGovernanceAuthorizationError(
                    "The case author cannot perform the independent clinical review."
                )
        elif payload.action in operational_actions:
            if actor.role != "admin":
                raise ProtocolGovernanceAuthorizationError(
                    "Only an administrator may perform operational governance review."
                )
            latest_clinical = next(
                (
                    item for item in reversed(existing)
                    if item.action in clinical_actions
                ),
                None,
            )
            if (
                latest_clinical is None
                or latest_clinical.action != "clinical_approve"
            ):
                raise ProtocolGovernanceConflictError(
                    "Operational review requires a current clinical approval."
                )

        review_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        stored = {
            "schema_version": 1,
            "id": review_id,
            "case_id": record.id,
            "case_sha256": record.sha256,
            "action": payload.action,
            "rationale": payload.rationale,
            "reviewer_user_id": actor.id,
            "created_at": created_at.isoformat(),
        }
        sha256 = evidence_digest(stored)
        try:
            review = ProtocolGovernanceRepository.create_review(
                db,
                id=review_id,
                case_id=record.id,
                case_sha256=record.sha256,
                action=payload.action,
                rationale=payload.rationale,
                reviewer_user_id=actor.id,
                payload=stored,
                sha256=sha256,
                created_at=created_at,
            )
            result_reviews = existing + [review]
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="protocol_governance_case",
                entity_id=record.id,
                event_type="protocol_governance_review_recorded",
                from_state=ProtocolGovernanceService._case_status(existing),
                to_state=ProtocolGovernanceService._case_status(result_reviews),
                message="An append-only protocol governance review was recorded.",
                event_data={
                    "action": payload.action,
                    "review_sha256": sha256,
                    "case_sha256": record.sha256,
                    "automatically_changes_protocol": False,
                },
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ProtocolGovernanceConflictError(
                "The governance review conflicted with another write."
            ) from error
        return ProtocolGovernanceService._to_read(db, record)

    @staticmethod
    def get_case(db: Session, case_id: str) -> ProtocolGovernanceCaseRead:
        record = ProtocolGovernanceRepository.get_case(db, case_id)
        if record is None:
            raise ProtocolGovernanceNotFoundError(
                f"Protocol governance case '{case_id}' was not found."
            )
        return ProtocolGovernanceService._to_read(db, record)

    @staticmethod
    def list_cases(db: Session) -> list[ProtocolGovernanceCaseRead]:
        return [
            ProtocolGovernanceService._to_read(db, item)
            for item in ProtocolGovernanceRepository.list_cases(db)
        ]
