from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.models.clinical_safety import (
    ClinicalSafetyEvaluation,
    ClinicalSafetyFinding,
)
from backend.app.models.clinical_safety_review import (
    ClinicalSafetyFindingReview,
)


class ClinicalSafetyFindingReviewRepository:
    """Flush-only persistence for append-only finding-review events."""

    @staticmethod
    def get_finding(
        db: Session,
        finding_id: str,
    ) -> ClinicalSafetyFinding | None:
        return db.scalar(
            select(ClinicalSafetyFinding)
            .options(
                joinedload(ClinicalSafetyFinding.evaluation).selectinload(
                    ClinicalSafetyEvaluation.findings
                )
            )
            .where(ClinicalSafetyFinding.id == finding_id)
        )

    @staticmethod
    def next_sequence(db: Session, finding_id: str) -> int:
        current = db.scalar(
            select(func.max(ClinicalSafetyFindingReview.sequence)).where(
                ClinicalSafetyFindingReview.finding_id == finding_id
            )
        )
        return (current or 0) + 1

    @staticmethod
    def list_by_finding(
        db: Session,
        finding_id: str,
    ) -> list[ClinicalSafetyFindingReview]:
        return list(
            db.scalars(
                select(ClinicalSafetyFindingReview)
                .where(ClinicalSafetyFindingReview.finding_id == finding_id)
                .order_by(ClinicalSafetyFindingReview.sequence.asc())
            ).all()
        )

    @staticmethod
    def list_all(
        db: Session,
    ) -> list[ClinicalSafetyFindingReview]:
        """Return every review row in deterministic chain order.

        The escalation queue validates complete chains before deciding whether a
        finding is open. It intentionally does not filter on mutable action
        columns in SQL, because doing so could hide a one-sided corrupt row.
        """

        return list(
            db.scalars(
                select(ClinicalSafetyFindingReview).order_by(
                    ClinicalSafetyFindingReview.finding_id.asc(),
                    ClinicalSafetyFindingReview.sequence.asc(),
                )
            ).all()
        )

    @staticmethod
    def get_by_id(
        db: Session,
        review_id: str,
    ) -> ClinicalSafetyFindingReview | None:
        return db.get(ClinicalSafetyFindingReview, review_id)

    @staticmethod
    def create(
        db: Session,
        *,
        review_id: str,
        finding_id: str,
        sequence: int,
        action: str,
        disposition: str | None,
        created_by_user_id: str,
        evaluation_result_sha256: str,
        rule_content_sha256: str,
        previous_review_sha256: str | None,
        payload: dict,
        sha256: str,
        created_at: datetime,
    ) -> ClinicalSafetyFindingReview:
        review = ClinicalSafetyFindingReview(
            id=review_id,
            finding_id=finding_id,
            sequence=sequence,
            action=action,
            disposition=disposition,
            created_by_user_id=created_by_user_id,
            evaluation_result_sha256=evaluation_result_sha256,
            rule_content_sha256=rule_content_sha256,
            previous_review_sha256=previous_review_sha256,
            payload=payload,
            sha256=sha256,
            created_at=created_at,
        )
        db.add(review)
        db.flush()
        db.refresh(review)
        return review
