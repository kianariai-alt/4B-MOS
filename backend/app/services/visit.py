from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.patient import (
    PatientRepository,
)
from backend.app.repositories.visit import (
    VisitRepository,
)
from backend.app.schemas.visit import (
    VisitCreate,
    VisitUpdate,
)
from backend.app.services.audit_context import (
    actor_data,
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
        actor: User | None = None,
    ) -> Visit:
        patient = PatientRepository.get_by_id(
            db,
            patient_id,
        )

        if patient is None:
            raise VisitPatientNotFoundError(
                f"Patient '{patient_id}' "
                "was not found."
            )

        visit = VisitRepository.create(
            db,
            patient_id,
            payload,
        )

        AuditLogRepository.create(
            db,
            entity_type="visit",
            entity_id=visit.id,
            event_type="visit_created",
            from_state=None,
            to_state=visit.status,
            message="Patient visit created.",
            event_data={
                "patient_id": patient_id,
                "body_region": (
                    visit.body_region
                ),
            },
            **actor_data(actor),
        )

        return visit

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
                f"Visit '{visit_id}' "
                "was not found."
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
                f"Patient '{patient_id}' "
                "was not found."
            )

        return (
            VisitRepository.list_by_patient(
                db,
                patient_id,
                skip=skip,
                limit=limit,
            )
        )

    @staticmethod
    def update_visit(
        db: Session,
        visit_id: str,
        payload: VisitUpdate,
        actor: User | None = None,
    ) -> Visit:
        visit = VisitService.get_visit(
            db,
            visit_id,
        )

        old_status = visit.status

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        changed_fields = list(
            update_data.keys()
        )

        updated_visit = (
            VisitRepository.update(
                db,
                visit,
                payload,
            )
        )

        new_status = updated_visit.status

        AuditLogRepository.create(
            db,
            entity_type="visit",
            entity_id=updated_visit.id,
            event_type="visit_updated",
            from_state=(
                old_status
                if old_status != new_status
                else None
            ),
            to_state=(
                new_status
                if old_status != new_status
                else None
            ),
            message="Patient visit updated.",
            event_data={
                "patient_id": (
                    updated_visit.patient_id
                ),
                "changed_fields": (
                    changed_fields
                ),
            },
            **actor_data(actor),
        )

        return updated_visit