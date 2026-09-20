"""Append-only clinician workflow for deterministic safety findings."""

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_safety import ClinicalSafetyFinding
from backend.app.models.clinical_safety_review import ClinicalSafetyFindingReview
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.clinical_safety_review import (
    ClinicalSafetyFindingReviewRepository,
)
from backend.app.schemas.clinical_safety_review import (
    SafetyFindingReviewCreate,
    SafetyFindingReviewPayloadRead,
    SafetyFindingReviewRead,
    SafetyFindingReviewTimelineRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_safety import (
    ClinicalSafetyAuthorizationError,
    ClinicalSafetyConflictError,
    ClinicalSafetyEvaluationService,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyNotFoundError,
)
from backend.app.services.session_finalization import evidence_digest


ACKNOWLEDGE_ROLES = {"physician", "nurse"}
ASSESS_ROLES = {"physician"}
ALLOWED_TRANSITIONS = {
    "unreviewed": {"acknowledged", "escalated", "assessed"},
    "acknowledged": {"escalated", "assessed"},
    "escalated": {"assessed"},
    "assessed": set(),
}


def _same_timestamp(payload_value: str, column_value: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(payload_value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if column_value.tzinfo is None:
        column_value = column_value.replace(tzinfo=timezone.utc)
    else:
        column_value = column_value.astimezone(timezone.utc)
    return parsed == column_value


class ClinicalSafetyFindingReviewService:
    @staticmethod
    def _require_actor(actor: User | None, *, action: str) -> User:
        allowed = ASSESS_ROLES if action == "assessed" else ACKNOWLEDGE_ROLES
        if actor is None or not actor.is_active or actor.role not in allowed:
            raise ClinicalSafetyAuthorizationError(
                "Only an active physician may assess a safety finding; an active "
                "physician or nurse may acknowledge or escalate one."
            )
        return actor

    @staticmethod
    def _load_finding(
        db: Session,
        visit_id: str,
        finding_id: str,
    ) -> ClinicalSafetyFinding:
        finding = ClinicalSafetyFindingReviewRepository.get_finding(db, finding_id)
        if finding is None or finding.evaluation.visit_id != visit_id:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety finding '{finding_id}' was not found for this visit."
            )
        ClinicalSafetyEvaluationService._verify(finding.evaluation)
        return finding

    @staticmethod
    def _validate_review(
        review: ClinicalSafetyFindingReview,
        *,
        finding: ClinicalSafetyFinding,
        expected_sequence: int,
        expected_previous_sha256: str | None,
    ) -> SafetyFindingReviewPayloadRead:
        evaluation = finding.evaluation
        try:
            raw = review.payload
            payload = SafetyFindingReviewPayloadRead.model_validate(deepcopy(raw))
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == review.sha256
                and review.sequence == expected_sequence
                and payload.id == review.id
                and payload.finding_id == review.finding_id == finding.id
                and payload.visit_id == evaluation.visit_id
                and payload.evaluation_id == evaluation.id
                and payload.evaluation_result_sha256
                == review.evaluation_result_sha256
                == evaluation.result_sha256
                and payload.rule_id == finding.rule_id
                and payload.rule_content_sha256
                == review.rule_content_sha256
                == finding.rule_content_sha256
                and payload.sequence == review.sequence
                and payload.previous_review_sha256
                == review.previous_review_sha256
                == expected_previous_sha256
                and payload.action == review.action
                and payload.disposition == review.disposition
                and payload.actor.actor_user_id == review.created_by_user_id
                and _same_timestamp(payload.created_at, review.created_at)
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            valid = False
            payload = None
        if not valid or payload is None:
            raise ClinicalSafetyIntegrityError(
                "Stored clinical safety finding review failed its integrity check."
            )
        return payload

    @staticmethod
    def _validate_chain(
        reviews: list[ClinicalSafetyFindingReview],
        *,
        finding: ClinicalSafetyFinding,
    ) -> list[SafetyFindingReviewRead]:
        output: list[SafetyFindingReviewRead] = []
        previous_sha256: str | None = None
        state = "unreviewed"
        for sequence, review in enumerate(reviews, start=1):
            if review.action not in ALLOWED_TRANSITIONS[state]:
                raise ClinicalSafetyIntegrityError(
                    "Stored clinical safety finding review has an invalid transition."
                )
            payload = ClinicalSafetyFindingReviewService._validate_review(
                review,
                finding=finding,
                expected_sequence=sequence,
                expected_previous_sha256=previous_sha256,
            )
            output.append(
                SafetyFindingReviewRead(
                    id=review.id,
                    finding_id=review.finding_id,
                    sequence=review.sequence,
                    action=review.action,
                    disposition=review.disposition,
                    created_by_user_id=review.created_by_user_id,
                    evaluation_result_sha256=review.evaluation_result_sha256,
                    rule_content_sha256=review.rule_content_sha256,
                    previous_review_sha256=review.previous_review_sha256,
                    sha256=review.sha256,
                    created_at=review.created_at,
                    payload=payload,
                )
            )
            state = review.action
            previous_sha256 = review.sha256
        return output

    @staticmethod
    def _timeline(
        db: Session,
        finding: ClinicalSafetyFinding,
    ) -> SafetyFindingReviewTimelineRead:
        reviews = ClinicalSafetyFindingReviewRepository.list_by_finding(
            db,
            finding.id,
        )
        validated = ClinicalSafetyFindingReviewService._validate_chain(
            reviews,
            finding=finding,
        )
        return SafetyFindingReviewTimelineRead(
            visit_id=finding.evaluation.visit_id,
            evaluation_id=finding.evaluation.id,
            evaluation_result_sha256=finding.evaluation.result_sha256,
            finding_id=finding.id,
            rule_id=finding.rule_id,
            rule_key=finding.rule_key,
            rule_version=finding.rule_version,
            severity=finding.severity,
            required_action=finding.action,
            review_status=(validated[-1].action if validated else "unreviewed"),
            reviews=validated,
        )

    @staticmethod
    @clinical_record_write
    def create(
        db: Session,
        visit_id: str,
        finding_id: str,
        payload: SafetyFindingReviewCreate,
        *,
        actor: User | None,
    ) -> SafetyFindingReviewTimelineRead:
        actor = ClinicalSafetyFindingReviewService._require_actor(
            actor,
            action=payload.action,
        )
        finding = ClinicalSafetyFindingReviewService._load_finding(
            db,
            visit_id,
            finding_id,
        )
        evaluation = finding.evaluation
        if payload.expected_evaluation_result_sha256 != evaluation.result_sha256:
            raise ClinicalSafetyConflictError(
                "The safety evaluation changed or does not match the reviewed "
                "snapshot; reload it before recording review."
            )
        existing = ClinicalSafetyFindingReviewRepository.list_by_finding(
            db,
            finding_id,
        )
        validated = ClinicalSafetyFindingReviewService._validate_chain(
            existing,
            finding=finding,
        )
        current_state = validated[-1].action if validated else "unreviewed"
        if payload.action not in ALLOWED_TRANSITIONS[current_state]:
            raise ClinicalSafetyConflictError(
                f"A finding in '{current_state}' state cannot transition to "
                f"'{payload.action}'. Record a new safety evaluation if the "
                "clinical context changed."
            )

        sequence = len(validated) + 1
        previous_sha256 = validated[-1].sha256 if validated else None
        review_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        stored_payload = {
            "schema_version": 1,
            "id": review_id,
            "visit_id": visit_id,
            "evaluation_id": evaluation.id,
            "evaluation_result_sha256": evaluation.result_sha256,
            "finding_id": finding.id,
            "rule_id": finding.rule_id,
            "rule_content_sha256": finding.rule_content_sha256,
            "sequence": sequence,
            "previous_review_sha256": previous_sha256,
            "action": payload.action,
            "disposition": payload.disposition,
            "reason_code": payload.reason_code,
            "note": payload.note,
            "actor": actor_data(actor),
            "created_at": created_at.isoformat(),
        }
        sha256 = evidence_digest(stored_payload)
        try:
            ClinicalSafetyFindingReviewRepository.create(
                db,
                review_id=review_id,
                finding_id=finding.id,
                sequence=sequence,
                action=payload.action,
                disposition=payload.disposition,
                created_by_user_id=actor.id,
                evaluation_result_sha256=evaluation.result_sha256,
                rule_content_sha256=finding.rule_content_sha256,
                previous_review_sha256=previous_sha256,
                payload=stored_payload,
                sha256=sha256,
                created_at=created_at,
            )
        except IntegrityError as error:
            raise ClinicalSafetyConflictError(
                "Another clinician changed this finding review timeline; reload "
                "before retrying."
            ) from error

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="clinical_safety_finding",
            entity_id=finding.id,
            event_type=f"clinical_safety_finding_{payload.action}",
            from_state=current_state,
            to_state=payload.action,
            message=(
                "An append-only clinician review event was recorded for a "
                "clinical safety finding."
            ),
            event_data={
                "visit_id": visit_id,
                "evaluation_id": evaluation.id,
                "evaluation_result_sha256": evaluation.result_sha256,
                "finding_review_id": review_id,
                "finding_review_sha256": sha256,
                "sequence": sequence,
                "action": payload.action,
                "disposition": payload.disposition,
                "reason_code": payload.reason_code,
                "changes_evaluation_result": False,
                "is_clinical_clearance": False,
            },
            **actor_data(actor),
        )
        return ClinicalSafetyFindingReviewService._timeline(db, finding)

    @staticmethod
    def get_timeline(
        db: Session,
        visit_id: str,
        finding_id: str,
    ) -> SafetyFindingReviewTimelineRead:
        finding = ClinicalSafetyFindingReviewService._load_finding(
            db,
            visit_id,
            finding_id,
        )
        return ClinicalSafetyFindingReviewService._timeline(db, finding)

    @staticmethod
    def get(
        db: Session,
        review_id: str,
    ) -> SafetyFindingReviewRead:
        review = ClinicalSafetyFindingReviewRepository.get_by_id(db, review_id)
        if review is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety finding review '{review_id}' was not found."
            )
        finding = ClinicalSafetyFindingReviewRepository.get_finding(
            db,
            review.finding_id,
        )
        if finding is None:
            raise ClinicalSafetyIntegrityError(
                "Stored clinical safety finding review has no finding."
            )
        timeline = ClinicalSafetyFindingReviewService._timeline(db, finding)
        for item in timeline.reviews:
            if item.id == review_id:
                return item
        raise ClinicalSafetyIntegrityError(
            "Stored clinical safety finding review is not in its review chain."
        )

    @staticmethod
    def list_audit_logs(
        db: Session,
        visit_id: str,
        finding_id: str,
    ) -> list[AuditLog]:
        ClinicalSafetyFindingReviewService._load_finding(
            db,
            visit_id,
            finding_id,
        )
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="clinical_safety_finding",
            entity_id=finding_id,
        )
