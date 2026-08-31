from datetime import (
    datetime,
    timezone,
)

from sqlalchemy.orm import Session

from backend.app.models.treatment_session import (
    TreatmentSession,
)
from backend.app.models.user import User
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)
from backend.app.services.audit_context import (
    actor_data,
)


ALLOWED_OPERATIONAL_TRANSITIONS = {
    "scheduled": {
        "checked_in",
        "cancelled",
    },
    "checked_in": {
        "ready",
        "cancelled",
    },
    "ready": {
        "in_treatment",
        "cancelled",
    },
    "in_treatment": {
        "completed",
        "cancelled",
    },
    "completed": {
        "discharged",
    },
    "discharged": set(),
    "cancelled": set(),
}


class SessionWorkflowNotFoundError(
    Exception
):
    pass


class SessionWorkflowConflictError(
    Exception
):
    pass


class SessionWorkflowService:
    @staticmethod
    def transition(
        db: Session,
        session_id: str,
        new_status: str,
        actor: User | None = None,
    ) -> TreatmentSession:
        treatment_session = (
            TreatmentSessionRepository
            .get_by_id(
                db,
                session_id,
            )
        )

        if treatment_session is None:
            raise SessionWorkflowNotFoundError(
                "Treatment session "
                f"'{session_id}' "
                "was not found."
            )

        old_status = (
            treatment_session
            .operational_status
        )

        allowed = (
            ALLOWED_OPERATIONAL_TRANSITIONS
            .get(
                old_status,
                set(),
            )
        )

        if new_status not in allowed:
            raise SessionWorkflowConflictError(
                "Invalid operational "
                "transition: "
                f"'{old_status}' -> "
                f"'{new_status}'."
            )

        now = datetime.now(
            timezone.utc
        )

        old_clinical_status = (
            treatment_session.status
        )

        if new_status == "checked_in":
            treatment_session.checked_in_at = (
                now
            )

        elif new_status == "ready":
            treatment_session.ready_at = now

        elif new_status == "in_treatment":
            if (
                treatment_session.status
                != "planned"
            ):
                raise (
                    SessionWorkflowConflictError(
                        "Clinical session must "
                        "be 'planned' before "
                        "treatment can start."
                    )
                )

            treatment_session.status = (
                "in_progress"
            )

            if (
                treatment_session.started_at
                is None
            ):
                treatment_session.started_at = (
                    now
                )

        elif new_status == "completed":
            if (
                treatment_session.status
                != "in_progress"
            ):
                raise (
                    SessionWorkflowConflictError(
                        "Clinical session must "
                        "be 'in_progress' "
                        "before completion."
                    )
                )

            treatment_session.status = (
                "completed"
            )

            if (
                treatment_session.completed_at
                is None
            ):
                treatment_session.completed_at = (
                    now
                )

        elif new_status == "discharged":
            if (
                treatment_session.status
                != "completed"
            ):
                raise (
                    SessionWorkflowConflictError(
                        "Clinical session must "
                        "be completed before "
                        "discharge."
                    )
                )

            treatment_session.discharged_at = (
                now
            )

        elif new_status == "cancelled":
            if (
                treatment_session.status
                not in {
                    "planned",
                    "in_progress",
                }
            ):
                raise (
                    SessionWorkflowConflictError(
                        "Completed clinical "
                        "sessions cannot be "
                        "cancelled."
                    )
                )

            treatment_session.status = (
                "cancelled"
            )

        treatment_session.operational_status = (
            new_status
        )

        new_clinical_status = (
            treatment_session.status
        )

        db.add(
            treatment_session
        )

        db.commit()

        db.refresh(
            treatment_session
        )

        if (
            old_clinical_status
            != new_clinical_status
        ):
            AuditLogRepository.create(
                db,
                entity_type=(
                    "treatment_session"
                ),
                entity_id=(
                    treatment_session.id
                ),
                event_type=(
                    "state_transition"
                ),
                from_state=(
                    old_clinical_status
                ),
                to_state=(
                    new_clinical_status
                ),
                message=(
                    "Clinical session status "
                    "changed through "
                    "operational workflow."
                ),
                event_data={
                    "treatment_id": (
                        treatment_session
                        .treatment_id
                    ),
                    "session_number": (
                        treatment_session
                        .session_number
                    ),
                    "source": (
                        "operational_workflow"
                    ),
                },
                **actor_data(actor),
            )

        AuditLogRepository.create(
            db,
            entity_type=(
                "treatment_session"
            ),
            entity_id=(
                treatment_session.id
            ),
            event_type=(
                "operational_transition"
            ),
            from_state=old_status,
            to_state=new_status,
            message=(
                "Session operational "
                f"status changed from "
                f"'{old_status}' to "
                f"'{new_status}'."
            ),
            event_data={
                "treatment_id": (
                    treatment_session
                    .treatment_id
                ),
                "session_number": (
                    treatment_session
                    .session_number
                ),
                "clinical_status": (
                    treatment_session.status
                ),
            },
            **actor_data(actor),
        )

        return treatment_session