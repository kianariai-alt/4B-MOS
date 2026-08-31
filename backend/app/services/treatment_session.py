from sqlalchemy.orm import Session

from backend.app.models.treatment_session import TreatmentSession
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)
from backend.app.schemas.treatment_session import (
    TreatmentSessionCreate,
    TreatmentSessionUpdate,
)


class TreatmentSessionNotFoundError(Exception):
    pass


class TreatmentForSessionNotFoundError(Exception):
    pass


class TreatmentSessionConflictError(Exception):
    pass


class TreatmentSessionService:
    @staticmethod
    def create_session(
        db: Session,
        treatment_id: str,
        payload: TreatmentSessionCreate,
    ) -> TreatmentSession:
        treatment = TreatmentRepository.get_by_id(
            db,
            treatment_id,
        )

        if treatment is None:
            raise TreatmentForSessionNotFoundError(
                f"Treatment '{treatment_id}' was not found."
            )

        existing = (
            TreatmentSessionRepository.get_by_treatment_and_number(
                db,
                treatment_id,
                payload.session_number,
            )
        )

        if existing is not None:
            raise TreatmentSessionConflictError(
                f"Session number {payload.session_number} "
                f"already exists for treatment '{treatment_id}'."
            )

        return TreatmentSessionRepository.create(
            db,
            treatment_id,
            payload,
        )

    @staticmethod
    def get_session(
        db: Session,
        session_id: str,
    ) -> TreatmentSession:
        treatment_session = (
            TreatmentSessionRepository.get_by_id(
                db,
                session_id,
            )
        )

        if treatment_session is None:
            raise TreatmentSessionNotFoundError(
                f"Treatment session '{session_id}' was not found."
            )

        return treatment_session

    @staticmethod
    def list_sessions(
        db: Session,
        treatment_id: str,
    ) -> list[TreatmentSession]:
        treatment = TreatmentRepository.get_by_id(
            db,
            treatment_id,
        )

        if treatment is None:
            raise TreatmentForSessionNotFoundError(
                f"Treatment '{treatment_id}' was not found."
            )

        return TreatmentSessionRepository.list_by_treatment(
            db,
            treatment_id,
        )

    @staticmethod
    def update_session(
        db: Session,
        session_id: str,
        payload: TreatmentSessionUpdate,
    ) -> TreatmentSession:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        if (
            payload.session_number is not None
            and payload.session_number
            != treatment_session.session_number
        ):
            existing = (
                TreatmentSessionRepository.get_by_treatment_and_number(
                    db,
                    treatment_session.treatment_id,
                    payload.session_number,
                )
            )

            if existing is not None:
                raise TreatmentSessionConflictError(
                    f"Session number {payload.session_number} "
                    "already exists for this treatment."
                )

        return TreatmentSessionRepository.update(
            db,
            treatment_session,
            payload,
        )