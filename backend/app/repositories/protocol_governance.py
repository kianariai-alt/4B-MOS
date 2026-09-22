from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.protocol_governance import (
    ProtocolGovernanceCase,
    ProtocolGovernanceReview,
    ProtocolGovernanceRelease,
    ProtocolGovernanceRecovery,
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
    def get_release(
        db: Session,
        release_id: str,
    ) -> ProtocolGovernanceRelease | None:
        return db.get(ProtocolGovernanceRelease, release_id)

    @staticmethod
    def get_release_by_case(
        db: Session,
        case_id: str,
    ) -> ProtocolGovernanceRelease | None:
        return db.scalar(
            select(ProtocolGovernanceRelease)
            .where(ProtocolGovernanceRelease.case_id == case_id)
            .limit(1)
        )

    @staticmethod
    def list_releases(db: Session) -> list[ProtocolGovernanceRelease]:
        return list(
            db.scalars(
                select(ProtocolGovernanceRelease).order_by(
                    ProtocolGovernanceRelease.created_at.desc(),
                    ProtocolGovernanceRelease.id.desc(),
                )
            ).all()
        )

    @staticmethod
    def create_release(
        db: Session,
        **kwargs,
    ) -> ProtocolGovernanceRelease:
        record = ProtocolGovernanceRelease(**kwargs)
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    @staticmethod
    def get_recovery_by_case(
        db: Session,
        case_id: str,
    ) -> ProtocolGovernanceRecovery | None:
        return db.scalar(
            select(ProtocolGovernanceRecovery)
            .where(ProtocolGovernanceRecovery.case_id == case_id)
            .limit(1)
        )

    @staticmethod
    def get_recovery_by_source_release(
        db: Session,
        source_release_id: str,
    ) -> ProtocolGovernanceRecovery | None:
        return db.scalar(
            select(ProtocolGovernanceRecovery)
            .where(
                ProtocolGovernanceRecovery.source_release_id
                == source_release_id
            )
            .limit(1)
        )

    @staticmethod
    def list_recoveries(db: Session) -> list[ProtocolGovernanceRecovery]:
        return list(
            db.scalars(
                select(ProtocolGovernanceRecovery).order_by(
                    ProtocolGovernanceRecovery.created_at.desc(),
                    ProtocolGovernanceRecovery.id.desc(),
                )
            ).all()
        )

    @staticmethod
    def create_recovery(
        db: Session,
        **kwargs,
    ) -> ProtocolGovernanceRecovery:
        record = ProtocolGovernanceRecovery(**kwargs)
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

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
