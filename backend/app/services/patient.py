from sqlalchemy.orm import Session

from backend.app.models.patient import Patient
from backend.app.models.user import User
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.patient import (
    PatientRepository,
)
from backend.app.schemas.patient import (
    PatientCreate,
    PatientUpdate,
)
from backend.app.services.audit_context import (
    actor_data,
)


class PatientNotFoundError(Exception):
    pass


class PatientCodeConflictError(Exception):
    pass


class PatientService:
    @staticmethod
    def create_patient(
        db: Session,
        payload: PatientCreate,
        actor: User | None = None,
    ) -> Patient:
        existing_patient = (
            PatientRepository.get_by_code(
                db,
                payload.patient_code,
            )
        )

        if existing_patient is not None:
            raise PatientCodeConflictError(
                f"Patient code "
                f"'{payload.patient_code}' "
                "already exists."
            )

        patient = PatientRepository.create(
            db,
            payload,
        )

        AuditLogRepository.create(
            db,
            entity_type="patient",
            entity_id=patient.id,
            event_type="patient_created",
            from_state=None,
            to_state="active",
            message="Patient record created.",
            event_data={
                "patient_code": (
                    patient.patient_code
                ),
            },
            **actor_data(actor),
        )

        return patient

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
                f"Patient '{patient_id}' "
                "was not found."
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
        actor: User | None = None,
    ) -> Patient:
        patient = PatientService.get_patient(
            db,
            patient_id,
        )

        changed_fields = list(
            payload.model_dump(
                exclude_unset=True,
            ).keys()
        )

        updated_patient = (
            PatientRepository.update(
                db,
                patient,
                payload,
            )
        )

        AuditLogRepository.create(
            db,
            entity_type="patient",
            entity_id=updated_patient.id,
            event_type="patient_updated",
            message="Patient record updated.",
            event_data={
                "changed_fields": (
                    changed_fields
                ),
            },
            **actor_data(actor),
        )

        return updated_patient

    @staticmethod
    def deactivate_patient(
        db: Session,
        patient_id: str,
        actor: User | None = None,
    ) -> Patient:
        patient = PatientService.get_patient(
            db,
            patient_id,
        )

        old_state = (
            "active"
            if patient.is_active
            else "inactive"
        )

        updated_patient = (
            PatientRepository.deactivate(
                db,
                patient,
            )
        )

        AuditLogRepository.create(
            db,
            entity_type="patient",
            entity_id=updated_patient.id,
            event_type=(
                "patient_deactivated"
            ),
            from_state=old_state,
            to_state="inactive",
            message=(
                "Patient record deactivated."
            ),
            event_data={
                "patient_code": (
                    updated_patient.patient_code
                ),
            },
            **actor_data(actor),
        )

        return updated_patient