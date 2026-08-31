from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.patient import (
    PatientRepository,
)
from backend.app.repositories.protocol import (
    ProtocolRepository,
)
from backend.app.repositories.treatment import (
    TreatmentRepository,
)
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)
from backend.app.repositories.visit import (
    VisitRepository,
)


class AuditEntityNotFoundError(Exception):
    pass


class AuditLogService:
    @staticmethod
    def _list_for_entity(
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
    ) -> list[AuditLog]:
        return AuditLogRepository.list_by_entity(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    @staticmethod
    def list_for_patient(
        db: Session,
        patient_id: str,
    ) -> list[AuditLog]:
        patient = PatientRepository.get_by_id(
            db,
            patient_id,
        )

        if patient is None:
            raise AuditEntityNotFoundError(
                f"Patient '{patient_id}' "
                "was not found."
            )

        return AuditLogService._list_for_entity(
            db,
            entity_type="patient",
            entity_id=patient_id,
        )

    @staticmethod
    def list_for_visit(
        db: Session,
        visit_id: str,
    ) -> list[AuditLog]:
        visit = VisitRepository.get_by_id(
            db,
            visit_id,
        )

        if visit is None:
            raise AuditEntityNotFoundError(
                f"Visit '{visit_id}' "
                "was not found."
            )

        return AuditLogService._list_for_entity(
            db,
            entity_type="visit",
            entity_id=visit_id,
        )

    @staticmethod
    def list_for_treatment(
        db: Session,
        treatment_id: str,
    ) -> list[AuditLog]:
        treatment = (
            TreatmentRepository.get_by_id(
                db,
                treatment_id,
            )
        )

        if treatment is None:
            raise AuditEntityNotFoundError(
                f"Treatment '{treatment_id}' "
                "was not found."
            )

        return AuditLogService._list_for_entity(
            db,
            entity_type="treatment",
            entity_id=treatment_id,
        )

    @staticmethod
    def list_for_protocol(
        db: Session,
        protocol_id: str,
    ) -> list[AuditLog]:
        protocol = ProtocolRepository.get_by_id(
            db,
            protocol_id,
        )

        if protocol is None:
            raise AuditEntityNotFoundError(
                f"Protocol '{protocol_id}' "
                "was not found."
            )

        return AuditLogService._list_for_entity(
            db,
            entity_type="protocol",
            entity_id=protocol_id,
        )

    @staticmethod
    def list_for_treatment_session(
        db: Session,
        session_id: str,
    ) -> list[AuditLog]:
        treatment_session = (
            TreatmentSessionRepository.get_by_id(
                db,
                session_id,
            )
        )

        if treatment_session is None:
            raise AuditEntityNotFoundError(
                f"Treatment session "
                f"'{session_id}' "
                "was not found."
            )

        return AuditLogService._list_for_entity(
            db,
            entity_type="treatment_session",
            entity_id=session_id,
        )