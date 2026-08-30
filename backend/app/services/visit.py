from sqlalchemy.orm import Session

from backend.app.models.visit import Visit
from backend.app.repositories.patient import PatientRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.visit import (
    VisitCreate,
    VisitUpdate,
)


class VisitNotFoundError(Exception):
    pass


class VisitPatientNotFoundError(Exception):
    pass


class VisitService:
    @staticmethod
    def create_visit(
        db: Session,
        patient_id: str,
        payload: VisitCreate,
    ) -> Visit:
        patient = PatientRepository.get_by_id(
            db,
            patient_id,
        )

        if patient is None:
            raise VisitPatientNotFoundError(
                f"Patient '{patient_id}' was not found."
            )

        return VisitRepository.create(
            db,
            patient_id,
            payload,
        )

    @staticmethod
    def get_visit(
        db: Session,
        visit_id: str,
    ) -> Visit:
        visit = VisitRepository.get_by_id(
            db,
            visit_id,
        )

        if visit is None:
            raise VisitNotFoundError(
                f"Visit '{visit_id}' was not found."
            )

        return visit

    @staticmethod
    def list_patient_visits(
        db: Session,
        patient_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Visit]:
        patient = PatientRepository.get_by_id(
            db,
            patient_id,
        )

        if patient is None:
            raise VisitPatientNotFoundError(
                f"Patient '{patient_id}' was not found."
            )

        return VisitRepository.list_by_patient(
            db,
            patient_id,
            skip=skip,
            limit=limit,
        )

    @staticmethod
    def update_visit(
        db: Session,
        visit_id: str,
        payload: VisitUpdate,
    ) -> Visit:
        visit = VisitService.get_visit(
            db,
            visit_id,
        )

        return VisitRepository.update(
            db,
            visit,
            payload,
        )