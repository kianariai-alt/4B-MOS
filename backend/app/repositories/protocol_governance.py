from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.protocol_governance import (
    ProtocolGovernanceCase,
    ProtocolGovernanceReview,
)


class ProtocolGovernanceRepository:
    @staticmethod
    def get_case(db: Session, case_id: str) -> ProtocolGovernanceCase | None:
        return db.get(ProtocolGovernanceCase, case_id)

    @staticmethod
    def list_cases(db: Session) -> list[ProtocolGovernanceCase]:
        return list(db.scalars(
            select(ProtocolGovernanceCase).order_by(
                ProtocolGovernanceCase.created_at.desc(),
                ProtocolGovernanceCase.id.desc(),
            )
        ).all())

    @staticmethod
    def list_reviews(db: Session, case_id: str) -> list[ProtocolGovernanceReview]:
        return list(db.scalars(
            select(ProtocolGovernanceReview)
            .where(ProtocolGovernanceReview.case_id == case_id)
            .order_by(
                ProtocolGovernanceReview.created_at.asc(),
                ProtocolGovernanceReview.id.asc(),
            )
        ).all())

    @staticmethod
    def create_case(db: Session, **kwargs) -> ProtocolGovernanceCase:
        record = ProtocolGovernanceCase(**kwargs)
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    @staticmethod
    def create_review(db: Session, **kwargs) -> ProtocolGovernanceReview:
        record = ProtocolGovernanceReview(**kwargs)
        db.add(record)
        db.flush()
        db.refresh(record)
        return record
