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
from backend.app.schemas.protocol import ProtocolCreate, ProtocolRead
from backend.app.schemas.protocol_governance import (
    ProtocolGovernanceCaseCreate,
    ProtocolGovernanceCaseRead,
    ProtocolGovernanceLineageRead,
    ProtocolGovernanceRecoveryCaseCreate,
    ProtocolGovernanceRecoveryExecute,
    ProtocolGovernanceRecoveryRead,
    ProtocolGovernanceReleaseExecute,
    ProtocolGovernanceReleaseRead,
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
                and raw.get("source_release_id") == record.source_release_id
                and raw.get("source_release_sha256")
                == record.source_release_sha256
                and raw.get("recovery_snapshot") == record.recovery_snapshot
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
    def _validate_release_record(record):
        try:
            raw = deepcopy(record.payload)
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("case_id") == record.case_id
                and raw.get("case_sha256") == record.case_sha256
                and raw.get("action") == record.action
                and raw.get("source_protocol_id") == record.source_protocol_id
                and raw.get("released_protocol_id") == record.released_protocol_id
                and raw.get("source_protocol_before")
                == record.source_protocol_before
                and raw.get("source_protocol_after")
                == record.source_protocol_after
                and raw.get("released_protocol_snapshot")
                == record.released_protocol_snapshot
                and raw.get("executed_by_user_id")
                == record.executed_by_user_id
                and raw.get("execution_note") == record.execution_note
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("preserves_history") is True
                and raw.get("is_rollback") is False
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ProtocolGovernanceIntegrityError(
                "Stored governed protocol release failed its integrity check."
            )
        return raw

    @staticmethod
    def _release_to_read(record) -> ProtocolGovernanceReleaseRead:
        raw = ProtocolGovernanceService._validate_release_record(record)
        return ProtocolGovernanceReleaseRead(
            id=record.id,
            case_id=record.case_id,
            case_sha256=record.case_sha256,
            action=record.action,
            source_protocol_id=record.source_protocol_id,
            released_protocol_id=record.released_protocol_id,
            source_protocol_before=deepcopy(record.source_protocol_before),
            source_protocol_after=deepcopy(record.source_protocol_after),
            released_protocol_snapshot=deepcopy(
                record.released_protocol_snapshot
            ),
            executed_by_user_id=record.executed_by_user_id,
            execution_note=raw["execution_note"],
            sha256=record.sha256,
            created_at=record.created_at,
        )

    @staticmethod
    def _validate_recovery_record(record):
        try:
            raw = deepcopy(record.payload)
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("case_id") == record.case_id
                and raw.get("case_sha256") == record.case_sha256
                and raw.get("source_release_id") == record.source_release_id
                and raw.get("source_release_sha256")
                == record.source_release_sha256
                and raw.get("action") == record.action
                and raw.get("deactivated_protocol_id")
                == record.deactivated_protocol_id
                and raw.get("reactivated_protocol_id")
                == record.reactivated_protocol_id
                and raw.get("before_snapshots") == record.before_snapshots
                and raw.get("after_snapshots") == record.after_snapshots
                and raw.get("executed_by_user_id")
                == record.executed_by_user_id
                and raw.get("execution_note") == record.execution_note
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("preserves_history") is True
                and raw.get("destructive_rollback") is False
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ProtocolGovernanceIntegrityError(
                "Stored governed protocol recovery failed its integrity check."
            )
        return raw

    @staticmethod
    def _recovery_to_read(record) -> ProtocolGovernanceRecoveryRead:
        raw = ProtocolGovernanceService._validate_recovery_record(record)
        return ProtocolGovernanceRecoveryRead(
            id=record.id,
            case_id=record.case_id,
            case_sha256=record.case_sha256,
            source_release_id=record.source_release_id,
            source_release_sha256=record.source_release_sha256,
            action=record.action,
            deactivated_protocol_id=record.deactivated_protocol_id,
            reactivated_protocol_id=record.reactivated_protocol_id,
            before_snapshots=deepcopy(record.before_snapshots),
            after_snapshots=deepcopy(record.after_snapshots),
            executed_by_user_id=record.executed_by_user_id,
            execution_note=raw["execution_note"],
            sha256=record.sha256,
            created_at=record.created_at,
        )

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
        release_record = ProtocolGovernanceRepository.get_release_by_case(
            db,
            record.id,
        )
        release = (
            ProtocolGovernanceService._release_to_read(release_record)
            if release_record is not None
            else None
        )
        recovery_record = ProtocolGovernanceRepository.get_recovery_by_case(
            db,
            record.id,
        )
        recovery = (
            ProtocolGovernanceService._recovery_to_read(recovery_record)
            if recovery_record is not None
            else None
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
            source_release_id=record.source_release_id,
            source_release_sha256=record.source_release_sha256,
            recovery_snapshot=deepcopy(record.recovery_snapshot),
            rationale=record.rationale,
            evidence_needed=list(record.evidence_needed),
            created_by_user_id=record.created_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
            reviews=review_reads,
            release=release,
            recovery=recovery,
            status=(
                "recovered"
                if recovery is not None
                else (
                    "released"
                    if release is not None
                    else ProtocolGovernanceService._case_status(review_reads)
                )
            ),
            requires_manual_protocol_action=(
                record.case_type in {
                    "revision_candidate",
                    "deactivation_candidate",
                    "reactivation_candidate",
                    "rollback_revision_candidate",
                }
                and release is None
                and recovery is None
            ),
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
            "source_release_id": None,
            "source_release_sha256": None,
            "recovery_snapshot": None,
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
                source_release_id=None,
                source_release_sha256=None,
                recovery_snapshot=None,
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
        if ProtocolGovernanceRepository.get_release_by_case(db, case_id):
            raise ProtocolGovernanceConflictError(
                "A released governance case is terminal and cannot accept "
                "additional reviews."
            )
        if ProtocolGovernanceRepository.get_recovery_by_case(db, case_id):
            raise ProtocolGovernanceConflictError(
                "A recovered governance case is terminal and cannot accept "
                "additional reviews."
            )
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
    def _protocol_snapshot(protocol) -> dict:
        return ProtocolRead.model_validate(protocol).model_dump(mode="json")

    @staticmethod
    def _matches_frozen_protocol_snapshot(
        current_snapshot: dict,
        frozen_snapshot: dict,
    ) -> bool:
        return all(
            current_snapshot.get(key) == value
            for key, value in frozen_snapshot.items()
        )

    @staticmethod
    def create_recovery_case(
        db: Session,
        release_id: str,
        payload: ProtocolGovernanceRecoveryCaseCreate,
        *,
        actor: User | None,
    ) -> ProtocolGovernanceCaseRead:
        if actor is None or not actor.is_active or actor.role != "physician":
            raise ProtocolGovernanceAuthorizationError(
                "Only an active physician may open a protocol recovery case."
            )

        release = ProtocolGovernanceRepository.get_release(db, release_id)
        if release is None:
            raise ProtocolGovernanceNotFoundError(
                f"Protocol governance release '{release_id}' was not found."
            )
        ProtocolGovernanceService._validate_release_record(release)
        if payload.expected_release_sha256 != release.sha256:
            raise ProtocolGovernanceConflictError(
                "The governed release hash changed; reload before recovery."
            )
        if ProtocolGovernanceRepository.get_recovery_by_source_release(
            db,
            release.id,
        ) is not None:
            raise ProtocolGovernanceConflictError(
                "This governed release has already been recovered."
            )

        try:
            learning = ClinicalLearningReviewService.get_review(db)
        except ClinicalLearningIntegrityError as error:
            raise ProtocolGovernanceIntegrityError(str(error)) from error
        if payload.expected_learning_review_sha256 != learning.review_sha256:
            raise ProtocolGovernanceConflictError(
                "The clinical learning review changed; reload it before "
                "opening a recovery case."
            )

        if release.action == "deactivate":
            target = ProtocolRepository.get_by_id(
                db,
                release.source_protocol_id,
            )
            if target is None:
                raise ProtocolGovernanceNotFoundError(
                    "The deactivated protocol is missing from the registry."
                )
            if target.is_active:
                raise ProtocolGovernanceConflictError(
                    "The deactivated protocol is already active."
                )
            primary = target
            case_type = "reactivation_candidate"
            recovery_action = "reactivate"
            recovery_snapshot = {
                "source_release": (
                    ProtocolGovernanceService._release_to_read(
                        release
                    ).model_dump(mode="json")
                ),
                "recovery_action": recovery_action,
                "reactivated_protocol_before": (
                    ProtocolGovernanceService._protocol_snapshot(target)
                ),
                "deactivated_protocol_before": None,
            }
        elif release.action == "publish_revision":
            previous = ProtocolRepository.get_by_id(
                db,
                release.source_protocol_id,
            )
            current = (
                ProtocolRepository.get_by_id(
                    db,
                    release.released_protocol_id,
                )
                if release.released_protocol_id is not None
                else None
            )
            if previous is None or current is None:
                raise ProtocolGovernanceNotFoundError(
                    "The revision lineage is incomplete in the registry."
                )
            if previous.is_active or not current.is_active:
                raise ProtocolGovernanceConflictError(
                    "The revision lineage is no longer in the state created "
                    "by the source release."
                )
            if (
                current.supersedes_protocol_id != previous.id
                or current.source_governance_case_id != release.case_id
                or current.source_governance_case_sha256
                != release.case_sha256
            ):
                raise ProtocolGovernanceIntegrityError(
                    "The revision lineage does not match its governed release."
                )
            primary = current
            case_type = "rollback_revision_candidate"
            recovery_action = "rollback_revision"
            recovery_snapshot = {
                "source_release": (
                    ProtocolGovernanceService._release_to_read(
                        release
                    ).model_dump(mode="json")
                ),
                "recovery_action": recovery_action,
                "reactivated_protocol_before": (
                    ProtocolGovernanceService._protocol_snapshot(previous)
                ),
                "deactivated_protocol_before": (
                    ProtocolGovernanceService._protocol_snapshot(current)
                ),
            }
        else:
            raise ProtocolGovernanceIntegrityError(
                "Unsupported governed release action."
            )

        source = next(
            (
                item for item in learning.protocols
                if item.protocol_code == primary.code
                and item.protocol_version == primary.version
            ),
            None,
        )
        if source is None:
            raise ProtocolGovernanceNotFoundError(
                "The recovery target is not present in the current clinical "
                "learning review."
            )

        case_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        protocol_snapshot = ProtocolGovernanceService._protocol_snapshot(
            primary
        )
        learning_snapshot = source.model_dump(mode="json")
        stored = {
            "schema_version": 1,
            "id": case_id,
            "protocol_code": primary.code,
            "protocol_version": primary.version,
            "treatment_type": primary.treatment_type,
            "case_type": case_type,
            "source_learning_review_sha256": learning.review_sha256,
            "protocol_snapshot": protocol_snapshot,
            "learning_snapshot": learning_snapshot,
            "proposed_protocol": None,
            "source_release_id": release.id,
            "source_release_sha256": release.sha256,
            "recovery_snapshot": recovery_snapshot,
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
                protocol_code=primary.code,
                protocol_version=primary.version,
                treatment_type=primary.treatment_type,
                case_type=case_type,
                source_learning_review_sha256=learning.review_sha256,
                protocol_snapshot=protocol_snapshot,
                learning_snapshot=learning_snapshot,
                proposed_protocol=None,
                source_release_id=release.id,
                source_release_sha256=release.sha256,
                recovery_snapshot=recovery_snapshot,
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
                event_type="protocol_governance_recovery_case_opened",
                from_state=None,
                to_state="awaiting_clinical_review",
                message=(
                    "A physician opened an immutable governed protocol "
                    "recovery case."
                ),
                event_data={
                    "case_type": case_type,
                    "source_release_id": release.id,
                    "source_release_sha256": release.sha256,
                    "recovery_action": recovery_action,
                    "case_sha256": sha256,
                    "automatically_changes_protocol": False,
                },
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ProtocolGovernanceConflictError(
                "The protocol recovery case conflicted with another write."
            ) from error

        return ProtocolGovernanceService._to_read(db, record)

    @staticmethod
    def execute_release(
        db: Session,
        case_id: str,
        payload: ProtocolGovernanceReleaseExecute,
        *,
        actor: User | None,
    ) -> ProtocolGovernanceCaseRead:
        if actor is None or not actor.is_active or actor.role != "admin":
            raise ProtocolGovernanceAuthorizationError(
                "Only an active administrator may execute a governed "
                "protocol release."
            )

        record = ProtocolGovernanceRepository.get_case(db, case_id)
        if record is None:
            raise ProtocolGovernanceNotFoundError(
                f"Protocol governance case '{case_id}' was not found."
            )
        ProtocolGovernanceService._validate_case_record(db, record)
        if payload.expected_case_sha256 != record.sha256:
            raise ProtocolGovernanceConflictError(
                "The governance case hash changed; reload before release."
            )

        if ProtocolGovernanceRepository.get_release_by_case(db, case_id):
            raise ProtocolGovernanceConflictError(
                "This governance case has already been released."
            )

        reviews = ProtocolGovernanceRepository.list_reviews(db, case_id)
        for review in reviews:
            ProtocolGovernanceService._validate_review_record(
                review,
                record.sha256,
            )
        if (
            ProtocolGovernanceService._case_status(reviews)
            != "approved_for_manual_action"
        ):
            raise ProtocolGovernanceConflictError(
                "The governance case is not approved for manual release."
            )

        if record.case_type not in {
            "revision_candidate",
            "deactivation_candidate",
        }:
            raise ProtocolGovernanceConflictError(
                "This governance case type does not permit a protocol release."
            )

        source = ProtocolRepository.get_by_code_version(
            db,
            record.protocol_code,
            record.protocol_version,
        )
        if source is None:
            raise ProtocolGovernanceNotFoundError(
                "The source protocol version is missing from the registry."
            )
        source_before = ProtocolGovernanceService._protocol_snapshot(source)
        if not ProtocolGovernanceService._matches_frozen_protocol_snapshot(
            source_before,
            record.protocol_snapshot,
        ):
            raise ProtocolGovernanceConflictError(
                "The source protocol changed after the governance case was "
                "opened; a new case is required."
            )
        if not source.is_active:
            raise ProtocolGovernanceConflictError(
                "The source protocol is already inactive."
            )

        release_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        released = None

        try:
            if record.case_type == "revision_candidate":
                if record.proposed_protocol is None:
                    raise ProtocolGovernanceIntegrityError(
                        "Revision governance case is missing its proposed "
                        "protocol snapshot."
                    )
                proposed = ProtocolCreate.model_validate(
                    record.proposed_protocol
                )
                if ProtocolRepository.get_by_code_version(
                    db,
                    proposed.code,
                    proposed.version,
                ) is not None:
                    raise ProtocolGovernanceConflictError(
                        "The governed revision version already exists."
                    )
                released = ProtocolRepository.create(
                    db,
                    proposed,
                    supersedes_protocol_id=source.id,
                    source_governance_case_id=record.id,
                    source_governance_case_sha256=record.sha256,
                    commit=False,
                )
                ProtocolRepository.deactivate(
                    db,
                    source,
                    commit=False,
                )
                action = "publish_revision"
            else:
                ProtocolRepository.deactivate(
                    db,
                    source,
                    commit=False,
                )
                action = "deactivate"

            source_after = ProtocolGovernanceService._protocol_snapshot(
                source
            )
            released_snapshot = (
                ProtocolGovernanceService._protocol_snapshot(released)
                if released is not None
                else None
            )

            stored = {
                "schema_version": 1,
                "id": release_id,
                "case_id": record.id,
                "case_sha256": record.sha256,
                "action": action,
                "source_protocol_id": source.id,
                "released_protocol_id": (
                    released.id if released is not None else None
                ),
                "source_protocol_before": source_before,
                "source_protocol_after": source_after,
                "released_protocol_snapshot": released_snapshot,
                "executed_by_user_id": actor.id,
                "execution_note": payload.execution_note,
                "created_at": created_at.isoformat(),
                "is_rollback": False,
                "preserves_history": True,
            }
            sha256 = evidence_digest(stored)
            release = ProtocolGovernanceRepository.create_release(
                db,
                id=release_id,
                case_id=record.id,
                case_sha256=record.sha256,
                action=action,
                source_protocol_id=source.id,
                released_protocol_id=(
                    released.id if released is not None else None
                ),
                source_protocol_before=source_before,
                source_protocol_after=source_after,
                released_protocol_snapshot=released_snapshot,
                executed_by_user_id=actor.id,
                execution_note=payload.execution_note,
                payload=stored,
                sha256=sha256,
                created_at=created_at,
            )

            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="protocol_governance_release",
                entity_id=release.id,
                event_type="governed_protocol_release_executed",
                from_state="approved_for_manual_action",
                to_state=action,
                message=(
                    "An administrator explicitly executed an approved "
                    "protocol governance release."
                ),
                event_data={
                    "case_id": record.id,
                    "case_sha256": record.sha256,
                    "release_sha256": sha256,
                    "action": action,
                    "source_protocol_id": source.id,
                    "released_protocol_id": (
                        released.id if released is not None else None
                    ),
                },
                **actor_data(actor),
            )
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="protocol",
                entity_id=source.id,
                event_type="protocol_superseded"
                if action == "publish_revision"
                else "protocol_governance_deactivated",
                from_state="active",
                to_state="inactive",
                message=(
                    "Protocol state changed through an approved governance "
                    "release."
                ),
                event_data={
                    "case_id": record.id,
                    "release_id": release.id,
                    "release_sha256": sha256,
                    "action": action,
                },
                **actor_data(actor),
            )
            if released is not None:
                AuditLogRepository.create(
                    db,
                    commit=False,
                    entity_type="protocol",
                    entity_id=released.id,
                    event_type="protocol_revision_published",
                    from_state=None,
                    to_state="active",
                    message=(
                        "A new protocol revision was published through an "
                        "approved governance release."
                    ),
                    event_data={
                        "case_id": record.id,
                        "release_id": release.id,
                        "release_sha256": sha256,
                        "supersedes_protocol_id": source.id,
                    },
                    **actor_data(actor),
                )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ProtocolGovernanceConflictError(
                "The governed release conflicted with another write."
            ) from error
        except Exception:
            db.rollback()
            raise

        return ProtocolGovernanceService._to_read(db, record)

    @staticmethod
    def execute_recovery(
        db: Session,
        case_id: str,
        payload: ProtocolGovernanceRecoveryExecute,
        *,
        actor: User | None,
    ) -> ProtocolGovernanceCaseRead:
        if actor is None or not actor.is_active or actor.role != "admin":
            raise ProtocolGovernanceAuthorizationError(
                "Only an active administrator may execute a governed "
                "protocol recovery."
            )

        record = ProtocolGovernanceRepository.get_case(db, case_id)
        if record is None:
            raise ProtocolGovernanceNotFoundError(
                f"Protocol governance case '{case_id}' was not found."
            )
        ProtocolGovernanceService._validate_case_record(db, record)
        if payload.expected_case_sha256 != record.sha256:
            raise ProtocolGovernanceConflictError(
                "The governance case hash changed; reload before recovery."
            )
        if record.case_type not in {
            "reactivation_candidate",
            "rollback_revision_candidate",
        }:
            raise ProtocolGovernanceConflictError(
                "This governance case type does not permit recovery."
            )
        if ProtocolGovernanceRepository.get_recovery_by_case(db, case_id):
            raise ProtocolGovernanceConflictError(
                "This governance case has already been recovered."
            )
        if (
            record.source_release_id is None
            or record.source_release_sha256 is None
            or record.recovery_snapshot is None
        ):
            raise ProtocolGovernanceIntegrityError(
                "The recovery governance case is missing source provenance."
            )

        source_release = ProtocolGovernanceRepository.get_release(
            db,
            record.source_release_id,
        )
        if source_release is None:
            raise ProtocolGovernanceNotFoundError(
                "The source governed release is missing."
            )
        ProtocolGovernanceService._validate_release_record(source_release)
        if source_release.sha256 != record.source_release_sha256:
            raise ProtocolGovernanceIntegrityError(
                "The source governed release hash does not match the "
                "recovery case."
            )
        if ProtocolGovernanceRepository.get_recovery_by_source_release(
            db,
            source_release.id,
        ):
            raise ProtocolGovernanceConflictError(
                "This governed release has already been recovered."
            )

        reviews = ProtocolGovernanceRepository.list_reviews(db, case_id)
        for review in reviews:
            ProtocolGovernanceService._validate_review_record(
                review,
                record.sha256,
            )
        if (
            ProtocolGovernanceService._case_status(reviews)
            != "approved_for_manual_action"
        ):
            raise ProtocolGovernanceConflictError(
                "The recovery case is not approved for manual recovery."
            )

        recovery_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        deactivated = None

        if record.case_type == "reactivation_candidate":
            reactivated = ProtocolRepository.get_by_id(
                db,
                source_release.source_protocol_id,
            )
            if reactivated is None:
                raise ProtocolGovernanceNotFoundError(
                    "The protocol selected for reactivation is missing."
                )
            current_reactivated = (
                ProtocolGovernanceService._protocol_snapshot(reactivated)
            )
            if (
                current_reactivated
                != record.recovery_snapshot[
                    "reactivated_protocol_before"
                ]
                or reactivated.is_active
            ):
                raise ProtocolGovernanceConflictError(
                    "The protocol state changed after the recovery case was "
                    "opened; a new case is required."
                )
            action = "reactivate"
        else:
            deactivated = (
                ProtocolRepository.get_by_id(
                    db,
                    source_release.released_protocol_id,
                )
                if source_release.released_protocol_id is not None
                else None
            )
            reactivated = ProtocolRepository.get_by_id(
                db,
                source_release.source_protocol_id,
            )
            if deactivated is None or reactivated is None:
                raise ProtocolGovernanceNotFoundError(
                    "The revision lineage is incomplete."
                )
            current_deactivated = (
                ProtocolGovernanceService._protocol_snapshot(deactivated)
            )
            current_reactivated = (
                ProtocolGovernanceService._protocol_snapshot(reactivated)
            )
            if (
                current_deactivated
                != record.recovery_snapshot[
                    "deactivated_protocol_before"
                ]
                or current_reactivated
                != record.recovery_snapshot[
                    "reactivated_protocol_before"
                ]
                or not deactivated.is_active
                or reactivated.is_active
            ):
                raise ProtocolGovernanceConflictError(
                    "The revision lineage changed after the recovery case was "
                    "opened; a new case is required."
                )
            if (
                deactivated.supersedes_protocol_id != reactivated.id
                or deactivated.source_governance_case_id
                != source_release.case_id
                or deactivated.source_governance_case_sha256
                != source_release.case_sha256
            ):
                raise ProtocolGovernanceIntegrityError(
                    "The revision lineage no longer matches the source release."
                )
            action = "rollback_revision"

        before_snapshots = {
            "deactivated_protocol": (
                ProtocolGovernanceService._protocol_snapshot(deactivated)
                if deactivated is not None
                else None
            ),
            "reactivated_protocol": (
                ProtocolGovernanceService._protocol_snapshot(reactivated)
            ),
        }

        try:
            if deactivated is not None:
                ProtocolRepository.deactivate(
                    db,
                    deactivated,
                    commit=False,
                )
            ProtocolRepository.activate(
                db,
                reactivated,
                commit=False,
            )

            after_snapshots = {
                "deactivated_protocol": (
                    ProtocolGovernanceService._protocol_snapshot(deactivated)
                    if deactivated is not None
                    else None
                ),
                "reactivated_protocol": (
                    ProtocolGovernanceService._protocol_snapshot(reactivated)
                ),
            }
            stored = {
                "schema_version": 1,
                "id": recovery_id,
                "case_id": record.id,
                "case_sha256": record.sha256,
                "source_release_id": source_release.id,
                "source_release_sha256": source_release.sha256,
                "action": action,
                "deactivated_protocol_id": (
                    deactivated.id if deactivated is not None else None
                ),
                "reactivated_protocol_id": reactivated.id,
                "before_snapshots": before_snapshots,
                "after_snapshots": after_snapshots,
                "executed_by_user_id": actor.id,
                "execution_note": payload.execution_note,
                "created_at": created_at.isoformat(),
                "preserves_history": True,
                "destructive_rollback": False,
            }
            sha256 = evidence_digest(stored)
            recovery = ProtocolGovernanceRepository.create_recovery(
                db,
                id=recovery_id,
                case_id=record.id,
                case_sha256=record.sha256,
                source_release_id=source_release.id,
                source_release_sha256=source_release.sha256,
                action=action,
                deactivated_protocol_id=(
                    deactivated.id if deactivated is not None else None
                ),
                reactivated_protocol_id=reactivated.id,
                before_snapshots=before_snapshots,
                after_snapshots=after_snapshots,
                executed_by_user_id=actor.id,
                execution_note=payload.execution_note,
                payload=stored,
                sha256=sha256,
                created_at=created_at,
            )
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="protocol_governance_recovery",
                entity_id=recovery.id,
                event_type="governed_protocol_recovery_executed",
                from_state="approved_for_manual_action",
                to_state=action,
                message=(
                    "An administrator explicitly executed an approved "
                    "governed protocol recovery."
                ),
                event_data={
                    "case_id": record.id,
                    "case_sha256": record.sha256,
                    "source_release_id": source_release.id,
                    "source_release_sha256": source_release.sha256,
                    "recovery_sha256": sha256,
                    "action": action,
                    "deactivated_protocol_id": (
                        deactivated.id if deactivated is not None else None
                    ),
                    "reactivated_protocol_id": reactivated.id,
                },
                **actor_data(actor),
            )
            if deactivated is not None:
                AuditLogRepository.create(
                    db,
                    commit=False,
                    entity_type="protocol",
                    entity_id=deactivated.id,
                    event_type="protocol_recovery_deactivated",
                    from_state="active",
                    to_state="inactive",
                    message=(
                        "Protocol version deactivated by an approved governed "
                        "recovery."
                    ),
                    event_data={
                        "recovery_id": recovery.id,
                        "source_release_id": source_release.id,
                        "recovery_sha256": sha256,
                    },
                    **actor_data(actor),
                )
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="protocol",
                entity_id=reactivated.id,
                event_type="protocol_reactivated",
                from_state="inactive",
                to_state="active",
                message=(
                    "Protocol version reactivated by an approved governed "
                    "recovery."
                ),
                event_data={
                    "recovery_id": recovery.id,
                    "source_release_id": source_release.id,
                    "recovery_sha256": sha256,
                    "action": action,
                },
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise ProtocolGovernanceConflictError(
                "The governed recovery conflicted with another write."
            ) from error
        except Exception:
            db.rollback()
            raise

        return ProtocolGovernanceService._to_read(db, record)

    @staticmethod
    def list_recoveries(
        db: Session,
    ) -> list[ProtocolGovernanceRecoveryRead]:
        return [
            ProtocolGovernanceService._recovery_to_read(item)
            for item in ProtocolGovernanceRepository.list_recoveries(db)
        ]

    @staticmethod
    def get_lineage(
        db: Session,
        protocol_id: str,
    ) -> ProtocolGovernanceLineageRead:
        protocol = ProtocolRepository.get_by_id(db, protocol_id)
        if protocol is None:
            raise ProtocolGovernanceNotFoundError(
                f"Protocol '{protocol_id}' was not found."
            )
        versions = ProtocolRepository.list_by_code(db, protocol.code)
        ids = {item.id for item in versions}
        if any(item.treatment_type != protocol.treatment_type for item in versions):
            raise ProtocolGovernanceIntegrityError(
                "Protocol lineage contains conflicting treatment types."
            )

        releases = []
        for record in ProtocolGovernanceRepository.list_releases(db):
            if (
                record.source_protocol_id in ids
                or record.released_protocol_id in ids
            ):
                releases.append(
                    ProtocolGovernanceService._release_to_read(record)
                )
        recoveries = []
        for record in ProtocolGovernanceRepository.list_recoveries(db):
            if (
                record.reactivated_protocol_id in ids
                or record.deactivated_protocol_id in ids
            ):
                recoveries.append(
                    ProtocolGovernanceService._recovery_to_read(record)
                )

        active_ids = [item.id for item in versions if item.is_active]
        if len(active_ids) > 1:
            raise ProtocolGovernanceIntegrityError(
                "Protocol lineage has more than one active version."
            )

        return ProtocolGovernanceLineageRead(
            protocol_code=protocol.code,
            treatment_type=protocol.treatment_type,
            versions=[
                ProtocolRead.model_validate(item)
                for item in versions
            ],
            releases=releases,
            recoveries=recoveries,
            active_protocol_ids=active_ids,
        )

    @staticmethod
    def list_releases(
        db: Session,
    ) -> list[ProtocolGovernanceReleaseRead]:
        return [
            ProtocolGovernanceService._release_to_read(item)
            for item in ProtocolGovernanceRepository.list_releases(db)
        ]

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
