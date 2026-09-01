from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.treatment_session import TreatmentSession
from backend.app.schemas.treatment_session import (
    TreatmentSessionCreate,
    TreatmentSessionUpdate,
)


class TreatmentSessionRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        session_id: str,
    ) -> TreatmentSession | None:
        return db.get(
            TreatmentSession,
            session_id,
        )

    @staticmethod
    def get_by_treatment_and_number(
        db: Session,
        treatment_id: str,
        session_number: int,
    ) -> TreatmentSession | None:
        statement = select(
            TreatmentSession
        ).where(
            TreatmentSession.treatment_id == treatment_id,
            TreatmentSession.session_number == session_number,
        )

        return db.scalar(statement)

    @staticmethod
    def list_by_treatment(
        db: Session,
        treatment_id: str,
    ) -> list[TreatmentSession]:
        statement = (
            select(TreatmentSession)
            .where(
                TreatmentSession.treatment_id == treatment_id
            )
            .order_by(
                TreatmentSession.session_number.asc()
            )
        )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def has_started_session_for_treatment(
        db: Session,
        treatment_id: str,
    ) -> bool:
        statement = (
            select(
                TreatmentSession.id
            )
            .where(
                TreatmentSession.treatment_id
                == treatment_id,
                TreatmentSession.started_at
                .is_not(None),
            )
            .limit(1)
        )

        return (
            db.scalar(statement)
            is not None
        )

    @staticmethod
    def create(
        db: Session,
        treatment_id: str,
        payload: TreatmentSessionCreate,
    ) -> TreatmentSession:
        create_data = payload.model_dump()

        treatment_session = TreatmentSession(
            treatment_id=treatment_id,
            status="planned",
            operational_status="scheduled",
            **create_data,
        )

        db.add(treatment_session)
        db.commit()
        db.refresh(treatment_session)

        return treatment_session

    @staticmethod
    def update(
        db: Session,
        treatment_session: TreatmentSession,
        payload: TreatmentSessionUpdate,
    ) -> TreatmentSession:
        update_data = payload.model_dump(
            exclude_unset=True,
        )

        for field_name, value in update_data.items():
            setattr(
                treatment_session,
                field_name,
                value,
            )

        db.add(treatment_session)
        db.commit()
        db.refresh(treatment_session)

        return treatment_session
