from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.treatment_session import TreatmentSession
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.treatment_session_completion import (
    TreatmentSessionCompletionGuardService,
)


WORKFLOW_ACTIONS = {
    "scheduled": (
        {
            "code": "check_in",
            "target_status": "checked_in",
            "label": "Check in",
            "is_primary": True,
        },
        {
            "code": "cancel",
            "target_status": "cancelled",
            "label": "Cancel",
            "is_primary": False,
        },
    ),
    "checked_in": (
        {
            "code": "mark_ready",
            "target_status": "ready",
            "label": "Mark ready",
            "is_primary": True,
        },
        {
            "code": "cancel",
            "target_status": "cancelled",
            "label": "Cancel",
            "is_primary": False,
        },
    ),
    "ready": (
        {
            "code": "start_treatment",
            "target_status": "in_treatment",
            "label": "Start treatment",
            "is_primary": True,
        },
        {
            "code": "cancel",
            "target_status": "cancelled",
            "label": "Cancel",
            "is_primary": False,
        },
    ),
    "in_treatment": (
        {
            "code": "complete",
            "target_status": "completed",
            "label": "Complete",
            "is_primary": True,
        },
        {
            "code": "cancel",
            "target_status": "cancelled",
            "label": "Cancel",
            "is_primary": False,
        },
    ),
    "completed": (
        {
            "code": "discharge",
            "target_status": "discharged",
            "label": "Discharge",
            "is_primary": True,
        },
    ),
    "discharged": (),
    "cancelled": (),
}


ALLOWED_OPERATIONAL_TRANSITIONS = {
    status: {
        action["target_status"]
        for action in actions
    }
    for status, actions in WORKFLOW_ACTIONS.items()
}


class SessionWorkflowNotFoundError(Exception):
    pass


class SessionWorkflowConflictError(Exception):
    pass


class SessionWorkflowService:
    @staticmethod
    def allowed_actions(
        operational_status: str,
    ) -> list[dict]:
        actions = WORKFLOW_ACTIONS.get(
            operational_status,
            (),
        )

        return [
            dict(action)
            for action in actions
        ]

    @staticmethod
    def transition(
        db: Session,
        session_id: str,
        new_status: str,
        actor: User | None = None,
    ) -> TreatmentSession:
        treatment_session = (
            TreatmentSessionRepository.get_by_id(
                db,
                session_id,
            )
        )

        if treatment_session is None:
            raise SessionWorkflowNotFoundError(
                f"Treatment session '{session_id}' "
                "was not found."
            )

        old_status = (
            treatment_session.operational_status
        )

        allowed = (
            ALLOWED_OPERATIONAL_TRANSITIONS.get(
                old_status,
                set(),
            )
        )

        if new_status not in allowed:
            raise SessionWorkflowConflictError(
                "Invalid operational transition: "
                f"'{old_status}' -> '{new_status}'."
            )

        now = datetime.now(timezone.utc)

        old_clinical_status = (
            treatment_session.status
        )

        if new_status == "checked_in":
            treatment_session.checked_in_at = now

        elif new_status == "ready":
            treatment_session.ready_at = now

        elif new_status == "in_treatment":
            if treatment_session.status != "planned":
                raise SessionWorkflowConflictError(
                    "Clinical session must be "
                    "'planned' before treatment "
                    "can start."
                )

            treatment_session.status = (
                "in_progress"
            )

            if treatment_session.started_at is None:
                treatment_session.started_at = now

        elif new_status == "completed":
            if (
                treatment_session.status
                != "in_progress"
            ):
                raise SessionWorkflowConflictError(
                    "Clinical session must be "
                    "'in_progress' before completion."
                )

            completion_check = (
                TreatmentSessionCompletionGuardService
                .evaluate(
                    db,
                    session_id,
                )
            )

            if not completion_check.can_complete:
                blocker_codes = ", ".join(
                    issue.code
                    for issue
                    in completion_check.issues
                    if issue.severity == "blocker"
                )

                raise SessionWorkflowConflictError(
                    "Session completion is blocked "
                    "by unresolved safety or data "
                    "requirements: "
                    f"{blocker_codes}."
                )

            treatment_session.status = "completed"

            if (
                treatment_session.completed_at
                is None
            ):
                treatment_session.completed_at = now

        elif new_status == "discharged":
            if (
                treatment_session.status
                != "completed"
            ):
                raise SessionWorkflowConflictError(
                    "Clinical session must be "
                    "completed before discharge."
                )

            treatment_session.discharged_at = now

        elif new_status == "cancelled":
            if treatment_session.status not in {
                "planned",
                "in_progress",
            }:
                raise SessionWorkflowConflictError(
                    "Completed clinical sessions "
                    "cannot be cancelled."
                )

            treatment_session.status = "cancelled"

        treatment_session.operational_status = (
            new_status
        )

        new_clinical_status = (
            treatment_session.status
        )

        db.add(treatment_session)
        db.commit()
        db.refresh(treatment_session)

        if (
            old_clinical_status
            != new_clinical_status
        ):
            AuditLogRepository.create(
                db,
                entity_type="treatment_session",
                entity_id=treatment_session.id,
                event_type="state_transition",
                from_state=old_clinical_status,
                to_state=new_clinical_status,
                message=(
                    "Clinical session status "
                    "changed through operational "
                    "workflow."
                ),
                event_data={
                    "treatment_id": (
                        treatment_session.treatment_id
                    ),
                    "session_number": (
                        treatment_session.session_number
                    ),
                    "source": (
                        "operational_workflow"
                    ),
                },
                **actor_data(actor),
            )

        AuditLogRepository.create(
            db,
            entity_type="treatment_session",
            entity_id=treatment_session.id,
            event_type="operational_transition",
            from_state=old_status,
            to_state=new_status,
            message=(
                "Session operational status "
                f"changed from '{old_status}' "
                f"to '{new_status}'."
            ),
            event_data={
                "treatment_id": (
                    treatment_session.treatment_id
                ),
                "session_number": (
                    treatment_session.session_number
                ),
                "clinical_status": (
                    treatment_session.status
                ),
            },
            **actor_data(actor),
        )

        return treatment_session