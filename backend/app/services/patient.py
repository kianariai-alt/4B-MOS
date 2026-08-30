from sqlalchemy.orm import Session

from backend.app.models.patient import Patient
from backend.app.repositories.patient import PatientRepository
from backend.app.schemas.patient import PatientCreate, PatientUpdate


class PatientNotFoundError(Exception):
    pass


class PatientCodeConflictError(Exception):
    pass


class PatientService:
    @staticmethod
    def create_patient(
        db: Session,
        payload: PatientCreate,
    ) -> Patient:
        existing_patient = PatientRepository.get_by_code(
            db,
            payload.patient_code,
        )

        if existing_patient is not None:
            raise PatientCodeConflictError(
                f"Patient code '{payload.patient_code}' already exists."
            )

        return PatientRepository.create(
            db,
            payload,
        )

    @staticmethod
    def get_patient(
        db: Session,
        patient_id: str,
    ) -> Patient:
        patient = PatientRepository.get_by_id(
            db,
            patient_id,
        )

        if patient is None:
            raise PatientNotFoundError(
                f"Patient '{patient_id}' was not found."
            )

        return patient

    @staticmethod
    def list_patients(
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Patient]:
        return PatientRepository.list(
            db,
            skip=skip,
            limit=limit,
        )

    @staticmethod
    def update_patient(
        db: Session,
        patient_id: str,
        payload: PatientUpdate,
    ) -> Patient:
        patient = PatientService.get_patient(
            db,
            patient_id,
        )

        return PatientRepository.update(
            db,
            patient,
            payload,
        )

    @staticmethod
    def deactivate_patient(
        db: Session,
        patient_id: str,
    ) -> Patient:
        patient = PatientService.get_patient(
            db,
            patient_id,
        )

        return PatientRepository.deactivate(
            db,
            patient,
        )