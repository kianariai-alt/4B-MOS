from sqlalchemy.orm import Session

from backend.app.models.protocol import (
    ProtocolTemplate,
)
from backend.app.models.user import User
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.protocol import (
    ProtocolRepository,
)
from backend.app.schemas.protocol import (
    ProtocolCreate,
)
from backend.app.services.audit_context import (
    actor_data,
)


class ProtocolNotFoundError(Exception):
    pass


class ProtocolVersionConflictError(Exception):
    pass


class ProtocolService:
    @staticmethod
    def create_protocol(
        db: Session,
        payload: ProtocolCreate,
        actor: User | None = None,
    ) -> ProtocolTemplate:
        existing = (
            ProtocolRepository.get_by_code_version(
                db,
                payload.code,
                payload.version,
            )
        )

        if existing is not None:
            raise ProtocolVersionConflictError(
                f"Protocol '{payload.code}' "
                f"version '{payload.version}' "
                "already exists."
            )

        protocol = ProtocolRepository.create(
            db,
            payload,
        )

        AuditLogRepository.create(
            db,
            entity_type="protocol",
            entity_id=protocol.id,
            event_type="protocol_created",
            from_state=None,
            to_state="active",
            message="Clinical protocol created.",
            event_data={
                "code": protocol.code,
                "version": protocol.version,
                "treatment_type": (
                    protocol.treatment_type
                ),
            },
            **actor_data(actor),
        )

        return protocol

    @staticmethod
    def get_protocol(
        db: Session,
        protocol_id: str,
    ) -> ProtocolTemplate:
        protocol = ProtocolRepository.get_by_id(
            db,
            protocol_id,
        )

        if protocol is None:
            raise ProtocolNotFoundError(
                f"Protocol '{protocol_id}' "
                "was not found."
            )

        return protocol

    @staticmethod
    def list_protocols(
        db: Session,
        treatment_type: str | None = None,
    ) -> list[ProtocolTemplate]:
        return ProtocolRepository.list(
            db,
            treatment_type=treatment_type,
        )

    @staticmethod
    def deactivate_protocol(
        db: Session,
        protocol_id: str,
        actor: User | None = None,
    ) -> ProtocolTemplate:
        protocol = ProtocolService.get_protocol(
            db,
            protocol_id,
        )

        old_state = (
            "active"
            if protocol.is_active
            else "inactive"
        )

        updated_protocol = (
            ProtocolRepository.deactivate(
                db,
                protocol,
            )
        )

        AuditLogRepository.create(
            db,
            entity_type="protocol",
            entity_id=updated_protocol.id,
            event_type="protocol_deactivated",
            from_state=old_state,
            to_state="inactive",
            message=(
                "Clinical protocol deactivated."
            ),
            event_data={
                "code": updated_protocol.code,
                "version": (
                    updated_protocol.version
                ),
            },
            **actor_data(actor),
        )

        return updated_protocol