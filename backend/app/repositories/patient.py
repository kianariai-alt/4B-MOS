from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.patient import Patient
from backend.app.schemas.patient import PatientCreate, PatientUpdate


class PatientRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        patient_id: str,
    ) -> Patient | None:
        return db.get(Patient, patient_id)

    @staticmethod
    def get_by_code(
        db: Session,
        patient_code: str,
    ) -> Patient | None:
        statement = select(Patient).where(
            Patient.patient_code == patient_code
        )

        return db.scalar(statement)

    @staticmethod
    def list(
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Patient]:
        statement = (
            select(Patient)
            .order_by(Patient.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        return list(db.scalars(statement).all())

    @staticmethod
    def create(
        db: Session,
        payload: PatientCreate,
    ) -> Patient:
        patient = Patient(
            **payload.model_dump(),
        )

        db.add(patient)
        db.commit()
        db.refresh(patient)

        return patient

    @staticmethod
    def update(
        db: Session,
        patient: Patient,
        payload: PatientUpdate,
    ) -> Patient:
        update_data = payload.model_dump(
            exclude_unset=True,
        )

        for field_name, value in update_data.items():
            setattr(
                patient,
                field_name,
                value,
            )

        db.add(patient)
        db.commit()
        db.refresh(patient)

        return patient

    @staticmethod
    def deactivate(
        db: Session,
        patient: Patient,
    ) -> Patient:
        patient.is_active = False

        db.add(patient)
        db.commit()
        db.refresh(patient)

        return patient