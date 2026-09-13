
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.transactions import atomic_write
from backend.app.models.treatment_session import TreatmentSession
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)
from backend.app.schemas.treatment_session import (
    TreatmentSessionCreate,
    TreatmentSessionRead,
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
    def _actor_data(
        actor: User | None,
    ) -> dict:
        if actor is None:
            return {
                "actor_user_id": None,
                "actor_username": None,
                "actor_display_name": None,
                "actor_role": None,
            }

        return {
            "actor_user_id": actor.id,
            "actor_username": actor.username,
            "actor_display_name": actor.display_name,
            "actor_role": actor.role,
        }

    @staticmethod
    @atomic_write
    def create_session(
        db: Session,
        treatment_id: str,
        payload: TreatmentSessionCreate,
        actor: User | None = None,
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

        try:
            treatment_session = (
                TreatmentSessionRepository.create(
                    db,
                    treatment_id,
                    payload,
                )
            )
        except IntegrityError as exc:
            raise TreatmentSessionConflictError(
                "Session creation conflicts with existing data."
            ) from exc

        AuditLogRepository.create(
            db,
            commit=False,
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
            **TreatmentSessionService._actor_data(
                actor
            ),
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
                "Invalid treatment session transition: "
                f"'{current_status}' -> '{new_status}'."
            )

    @staticmethod
    @atomic_write
    def update_session(
        db: Session,
        session_id: str,
        payload: TreatmentSessionUpdate,
        actor: User | None = None,
    ) -> TreatmentSession:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )
        if treatment_session.status in {
            "completed",
            "cancelled",
        }:
            raise TreatmentSessionConflictError(
                "Completed or cancelled treatment "
                "sessions are immutable."
            )

        workflow_managed_fields = {
            "status",
            "started_at",
            "completed_at",
        }

        requested_workflow_fields = (
            workflow_managed_fields.intersection(
                payload.model_fields_set
            )
        )

        if requested_workflow_fields:
            fields = ", ".join(
                sorted(
                    requested_workflow_fields
                )
            )

            raise (
                InvalidTreatmentSessionTransitionError(
                    "Session lifecycle fields "
                    "must be changed through "
                    "the operational workflow: "
                    f"{fields}."
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

        update_data = payload.model_dump(
            exclude_unset=True,
        )
        changed_fields = sorted(
            field for field, value in update_data.items()
            if getattr(treatment_session, field) != value
        )
        if not changed_fields:
            return treatment_session

        before = TreatmentSessionRead.model_validate(
            treatment_session
        ).model_dump(mode="json", include=set(changed_fields))

        try:
            updated_session = TreatmentSessionRepository.update(
                db, treatment_session, payload,
            )
        except IntegrityError as exc:
            raise TreatmentSessionConflictError(
                "Session update conflicts with existing data."
            ) from exc

        after = TreatmentSessionRead.model_validate(
            updated_session
        ).model_dump(mode="json", include=set(changed_fields))

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="treatment_session",
            entity_id=updated_session.id,
            event_type="session_updated",
            from_state=updated_session.status,
            to_state=updated_session.status,
            message="Treatment session clinical documentation updated.",
            event_data={
                "treatment_id": updated_session.treatment_id,
                "session_number": updated_session.session_number,
                "changed_fields": changed_fields,
                "before": before,
                "after": after,
            },
            **TreatmentSessionService._actor_data(actor),
        )

        return updated_session
