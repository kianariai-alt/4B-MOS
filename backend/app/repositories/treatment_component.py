from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import Session

from backend.app.models.treatment_component import (
    TreatmentComponent,
)
from backend.app.models.treatment_session_component import (
    TreatmentSessionComponent,
)
from backend.app.schemas.treatment_component import (
    TreatmentComponentCreate,
    TreatmentComponentUpdate,
)


class TreatmentComponentRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        component_id: str,
    ) -> TreatmentComponent | None:
        return db.get(
            TreatmentComponent,
            component_id,
        )

    @staticmethod
    def list_by_treatment(
        db: Session,
        treatment_id: str,
    ) -> list[TreatmentComponent]:
        statement = (
            select(TreatmentComponent)
            .where(
                TreatmentComponent.treatment_id
                == treatment_id
            )
            .order_by(
                TreatmentComponent.sequence.asc(),
                TreatmentComponent.created_at.asc(),
            )
        )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def get_by_treatment_material(
        db: Session,
        treatment_id: str,
        material_id: str,
    ) -> TreatmentComponent | None:
        statement = select(
            TreatmentComponent
        ).where(
            TreatmentComponent.treatment_id
            == treatment_id,
            TreatmentComponent.material_id
            == material_id,
        )

        return db.scalar(statement)

    @staticmethod
    def get_by_treatment_sequence(
        db: Session,
        treatment_id: str,
        sequence: int,
    ) -> TreatmentComponent | None:
        statement = select(
            TreatmentComponent
        ).where(
            TreatmentComponent.treatment_id
            == treatment_id,
            TreatmentComponent.sequence
            == sequence,
        )

        return db.scalar(statement)

    @staticmethod
    def has_session_component_references(
        db: Session,
        component_id: str,
    ) -> bool:
        statement = (
            select(
                TreatmentSessionComponent.id
            )
            .where(
                TreatmentSessionComponent
                .treatment_component_id
                == component_id
            )
            .limit(1)
        )

        return (
            db.scalar(statement)
            is not None
        )

    @staticmethod
    def next_sequence(
        db: Session,
        treatment_id: str,
    ) -> int:
        statement = select(
            func.max(
                TreatmentComponent.sequence
            )
        ).where(
            TreatmentComponent.treatment_id
            == treatment_id
        )

        current_max = db.scalar(statement)

        if current_max is None:
            return 1

        return int(current_max) + 1

    @staticmethod
    def create(
        db: Session,
        treatment_id: str,
        payload: TreatmentComponentCreate,
        *,
        sequence: int,
        unit: str | None,
    ) -> TreatmentComponent:
        component = TreatmentComponent(
            treatment_id=treatment_id,
            material_id=payload.material_id,
            planned_amount=(
                payload.planned_amount
            ),
            unit=unit,
            sequence=sequence,
            notes=payload.notes,
        )

        db.add(component)
        db.commit()
        db.refresh(component)

        return component

    @staticmethod
    def update(
        db: Session,
        component: TreatmentComponent,
        payload: TreatmentComponentUpdate,
    ) -> TreatmentComponent:
        update_data = payload.model_dump(
            exclude_unset=True,
        )

        for field_name, value in (
            update_data.items()
        ):
            setattr(
                component,
                field_name,
                value,
            )

        db.add(component)
        db.commit()
        db.refresh(component)

        return component

    @staticmethod
    def delete(
        db: Session,
        component: TreatmentComponent,
    ) -> None:
        db.delete(component)
        db.commit()
