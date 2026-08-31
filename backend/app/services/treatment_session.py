from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.treatment_session import TreatmentSession
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)
from backend.app.schemas.treatment_session import (
    TreatmentSessionCreate,
    TreatmentSessionUpdate,
)


ALLOWED_SESSION_TRANSITIONS = {
    "planned": {
        "in_progress",
        "cancelled",
    },
    "in_progress": {
        "completed",
        "cancelled",
    },
    "completed": set(),
    "cancelled": set(),
}


class TreatmentSessionNotFoundError(Exception):
    pass


class TreatmentForSessionNotFoundError(Exception):
    pass


class TreatmentSessionConflictError(Exception):
    pass


class InvalidTreatmentSessionTransitionError(Exception):
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

        treatment_session = (
            TreatmentSessionRepository.create(
                db,
                treatment_id,
                payload,
            )
        )

        AuditLogRepository.create(
            db,
            entity_type="treatment_session",
            entity_id=treatment_session.id,
            event_type="session_created",
            from_state=None,
            to_state=treatment_session.status,
            message="Treatment session created.",
            event_data={
                "treatment_id": treatment_id,
                "session_number": treatment_session.session_number,
            },
        )

        return treatment_session

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
    def _validate_transition(
        current_status: str,
        new_status: str,
    ) -> None:
        if current_status == new_status:
            return

        allowed = ALLOWED_SESSION_TRANSITIONS.get(
            current_status,
            set(),
        )

        if new_status not in allowed:
            raise InvalidTreatmentSessionTransitionError(
                f"Invalid treatment session transition: "
                f"'{current_status}' -> '{new_status}'."
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

        old_status = treatment_session.status
        new_status = payload.status

        if new_status is not None:
            TreatmentSessionService._validate_transition(
                old_status,
                new_status,
            )

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        transition_occurred = (
            new_status is not None
            and new_status != old_status
        )

        if transition_occurred:
            now = datetime.now(timezone.utc)

            if new_status == "in_progress":
                if update_data.get("started_at") is None:
                    update_data["started_at"] = now

            if new_status == "completed":
                if update_data.get("completed_at") is None:
                    update_data["completed_at"] = now

        normalized_payload = TreatmentSessionUpdate(
            **update_data
        )

        updated_session = (
            TreatmentSessionRepository.update(
                db,
                treatment_session,
                normalized_payload,
            )
        )

        if transition_occurred:
            AuditLogRepository.create(
                db,
                entity_type="treatment_session",
                entity_id=updated_session.id,
                event_type="state_transition",
                from_state=old_status,
                to_state=new_status,
                message=(
                    f"Session status changed from "
                    f"'{old_status}' to '{new_status}'."
                ),
                event_data={
                    "session_number": updated_session.session_number,
                    "treatment_id": updated_session.treatment_id,
                },
            )

        return updated_session