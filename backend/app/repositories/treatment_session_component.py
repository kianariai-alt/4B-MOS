from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import Session

from backend.app.models.treatment_session_component import (
    TreatmentSessionComponent,
)
from backend.app.schemas.treatment_session_component import (
    TreatmentSessionComponentCreate,
    TreatmentSessionComponentUpdate,
)


class TreatmentSessionComponentRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        component_id: str,
    ) -> TreatmentSessionComponent | None:
        return db.get(
            TreatmentSessionComponent,
            component_id,
        )

    @staticmethod
    def list_by_session(
        db: Session,
        session_id: str,
    ) -> list[TreatmentSessionComponent]:
        statement = (
            select(
                TreatmentSessionComponent
            )
            .where(
                TreatmentSessionComponent
                .treatment_session_id
                == session_id
            )
            .order_by(
                TreatmentSessionComponent
                .sequence.asc(),
                TreatmentSessionComponent
                .created_at.asc(),
            )
        )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def get_by_session_sequence(
        db: Session,
        session_id: str,
        sequence: int,
    ) -> TreatmentSessionComponent | None:
        statement = select(
            TreatmentSessionComponent
        ).where(
            TreatmentSessionComponent
            .treatment_session_id
            == session_id,
            TreatmentSessionComponent
            .sequence
            == sequence,
        )

        return db.scalar(statement)

    @staticmethod
    def next_sequence(
        db: Session,
        session_id: str,
    ) -> int:
        statement = select(
            func.max(
                TreatmentSessionComponent
                .sequence
            )
        ).where(
            TreatmentSessionComponent
            .treatment_session_id
            == session_id
        )

        current_max = db.scalar(
            statement
        )

        if current_max is None:
            return 1

        return int(current_max) + 1

    @staticmethod
    def create(
        db: Session,
        session_id: str,
        payload: TreatmentSessionComponentCreate,
        *,
        sequence: int,
        unit: str | None,
    ) -> TreatmentSessionComponent:
        create_data = payload.model_dump()

        create_data["sequence"] = sequence
        create_data["unit"] = unit

        component = (
            TreatmentSessionComponent(
                treatment_session_id=session_id,
                **create_data,
            )
        )

        db.add(component)
        db.commit()
        db.refresh(component)

        return component

    @staticmethod
    def update(
        db: Session,
        component: TreatmentSessionComponent,
        payload: TreatmentSessionComponentUpdate,
    ) -> TreatmentSessionComponent:
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
        component: TreatmentSessionComponent,
    ) -> None:
        db.delete(component)
        db.commit()
