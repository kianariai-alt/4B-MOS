from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.treatment import Treatment
from backend.app.schemas.treatment import (
    TreatmentCreate,
    TreatmentUpdate,
)


class TreatmentRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        treatment_id: str,
    ) -> Treatment | None:
        return db.get(
            Treatment,
            treatment_id,
        )

    @staticmethod
    def list_by_visit(
        db: Session,
        visit_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Treatment]:
        statement = (
            select(Treatment)
            .where(
                Treatment.visit_id == visit_id
            )
            .order_by(
                Treatment.session_number.asc(),
                Treatment.created_at.asc(),
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
        visit_id: str,
        payload: TreatmentCreate,
        protocol_name: str | None = None,
        protocol_version: str | None = None,
        protocol_snapshot: dict | None = None,
    ) -> Treatment:
        treatment = Treatment(
            visit_id=visit_id,
            protocol_template_id=payload.protocol_template_id,
            protocol_name=protocol_name,
            protocol_version=protocol_version,
            protocol_snapshot=protocol_snapshot,
            treatment_type=payload.treatment_type,
            session_number=payload.session_number,
            body_region=payload.body_region,
            dose_or_volume=payload.dose_or_volume,
            execution_parameters=payload.execution_parameters,
            notes=payload.notes,
        )

        db.add(treatment)
        db.commit()
        db.refresh(treatment)

        return treatment

    @staticmethod
    def update(
        db: Session,
        treatment: Treatment,
        payload: TreatmentUpdate,
    ) -> Treatment:
        update_data = payload.model_dump(
            exclude_unset=True,
        )

        for field_name, value in update_data.items():
            setattr(
                treatment,
                field_name,
                value,
            )

        db.add(treatment)
        db.commit()
        db.refresh(treatment)

        return treatment