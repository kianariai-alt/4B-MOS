from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.treatment_session import (
    TreatmentSessionRepository,
)


class AuditEntityNotFoundError(Exception):
    pass


class AuditLogService:
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
                f"Treatment session '{session_id}' was not found."
            )

        return AuditLogRepository.list_by_entity(
            db,
            entity_type="treatment_session",
            entity_id=session_id,
        )