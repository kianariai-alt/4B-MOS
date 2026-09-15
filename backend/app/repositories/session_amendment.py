from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.session_amendment import (
    SessionAmendment,
    SessionAmendmentReview,
)


class SessionAmendmentRepository:
    """Flush-only persistence for append-only amendment records."""

    @staticmethod
    def next_sequence(db: Session, session_id: str) -> int:
        current = db.scalar(
            select(func.max(SessionAmendment.sequence)).where(
                SessionAmendment.session_id == session_id
            )
        )
        return (current or 0) + 1

    @staticmethod
    def create(
        db: Session,
        *,
        amendment_id: str,
        session_id: str,
        sequence: int,
        created_at: datetime,
        payload: dict,
        sha256: str,
    ) -> SessionAmendment:
        record = SessionAmendment(
            id=amendment_id,
            session_id=session_id,
            sequence=sequence,
            created_at=created_at,
            payload=payload,
            sha256=sha256,
        )
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    @staticmethod
    def get_by_id(db: Session, amendment_id: str) -> SessionAmendment | None:
        return db.get(SessionAmendment, amendment_id)

    @staticmethod
    def list_by_session(db: Session, session_id: str) -> list[SessionAmendment]:
        return list(
            db.scalars(
                select(SessionAmendment)
                .where(SessionAmendment.session_id == session_id)
                .order_by(SessionAmendment.sequence.asc())
            ).all()
        )

    @staticmethod
    def get_review(db: Session, amendment_id: str) -> SessionAmendmentReview | None:
        return db.get(SessionAmendmentReview, amendment_id)

    @staticmethod
    def create_review(
        db: Session,
        *,
        amendment_id: str,
        decision: str,
        reviewed_at: datetime,
        payload: dict,
        sha256: str,
    ) -> SessionAmendmentReview:
        review = SessionAmendmentReview(
            amendment_id=amendment_id,
            decision=decision,
            reviewed_at=reviewed_at,
            payload=payload,
            sha256=sha256,
        )
        db.add(review)
        db.flush()
        db.refresh(review)
        return review
