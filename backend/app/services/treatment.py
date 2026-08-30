from sqlalchemy.orm import Session

from backend.app.models.treatment import Treatment
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.treatment import (
    TreatmentCreate,
    TreatmentUpdate,
)


class TreatmentNotFoundError(Exception):
    pass


class TreatmentVisitNotFoundError(Exception):
    pass


class TreatmentService:
    @staticmethod
    def create_treatment(
        db: Session,
        visit_id: str,
        payload: TreatmentCreate,
    ) -> Treatment:
        visit = VisitRepository.get_by_id(
            db,
            visit_id,
        )

        if visit is None:
            raise TreatmentVisitNotFoundError(
                f"Visit '{visit_id}' was not found."
            )

        return TreatmentRepository.create(
            db,
            visit_id,
            payload,
        )

    @staticmethod
    def get_treatment(
        db: Session,
        treatment_id: str,
    ) -> Treatment:
        treatment = TreatmentRepository.get_by_id(
            db,
            treatment_id,
        )

        if treatment is None:
            raise TreatmentNotFoundError(
                f"Treatment '{treatment_id}' was not found."
            )

        return treatment

    @staticmethod
    def list_visit_treatments(
        db: Session,
        visit_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Treatment]:
        visit = VisitRepository.get_by_id(
            db,
            visit_id,
        )

        if visit is None:
            raise TreatmentVisitNotFoundError(
                f"Visit '{visit_id}' was not found."
            )

        return TreatmentRepository.list_by_visit(
            db,
            visit_id,
            skip=skip,
            limit=limit,
        )

    @staticmethod
    def update_treatment(
        db: Session,
        treatment_id: str,
        payload: TreatmentUpdate,
    ) -> Treatment:
        treatment = TreatmentService.get_treatment(
            db,
            treatment_id,
        )

        return TreatmentRepository.update(
            db,
            treatment,
            payload,
        )