from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.visit import Visit
from backend.app.schemas.visit import (
    VisitCreate,
    VisitUpdate,
)


class VisitRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        visit_id: str,
    ) -> Visit | None:
        return db.get(
            Visit,
            visit_id,
        )

    @staticmethod
    def list_by_patient(
        db: Session,
        patient_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Visit]:
        statement = (
            select(Visit)
            .where(
                Visit.patient_id == patient_id
            )
            .order_by(
                Visit.visit_date.desc()
            )
            .offset(skip)
            .limit(limit)
        )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def create(
        db: Session,
        patient_id: str,
        payload: VisitCreate,
    ) -> Visit:
        visit = Visit(
            patient_id=patient_id,
            **payload.model_dump(),
        )

        db.add(visit)
        db.commit()
        db.refresh(visit)

        return visit

    @staticmethod
    def update(
        db: Session,
        visit: Visit,
        payload: VisitUpdate,
    ) -> Visit:
        update_data = payload.model_dump(
            exclude_unset=True,
        )

        for field_name, value in update_data.items():
            setattr(
                visit,
                field_name,
                value,
            )

        db.add(visit)
        db.commit()
        db.refresh(visit)

        return visit