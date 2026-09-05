from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog


class AuditLogRepository:
    @staticmethod
    def create(
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor_user_id: str | None = None,
        actor_username: str | None = None,
        actor_display_name: str | None = None,
        actor_role: str | None = None,
        from_state: str | None = None,
        to_state: str | None = None,
        message: str | None = None,
        event_data: dict | None = None,
        commit: bool = True,
    ) -> AuditLog:
        audit_log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_username=actor_username,
            actor_display_name=actor_display_name,
            actor_role=actor_role,
            from_state=from_state,
            to_state=to_state,
            message=message,
            event_data=event_data,
        )

        db.add(audit_log)
        if commit:
            db.commit()
        else:
            db.flush()
        db.refresh(audit_log)

        return audit_log

    @staticmethod
    def list_by_entity(
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
    ) -> list[AuditLog]:
        statement = (
            select(AuditLog)
            .where(
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
            )
            .order_by(
                AuditLog.created_at.asc(),
                AuditLog.id.asc(),
            )
        )

        return list(
            db.scalars(statement).all()
        )
