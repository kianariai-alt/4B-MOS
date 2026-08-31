from sqlalchemy.orm import Session

from backend.app.models.protocol import ProtocolTemplate
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.schemas.protocol import ProtocolCreate


class ProtocolNotFoundError(Exception):
    pass


class ProtocolVersionConflictError(Exception):
    pass


class ProtocolService:
    @staticmethod
    def create_protocol(
        db: Session,
        payload: ProtocolCreate,
    ) -> ProtocolTemplate:
        existing = ProtocolRepository.get_by_code_version(
            db,
            payload.code,
            payload.version,
        )

        if existing is not None:
            raise ProtocolVersionConflictError(
                f"Protocol '{payload.code}' version "
                f"'{payload.version}' already exists."
            )

        return ProtocolRepository.create(
            db,
            payload,
        )

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
                f"Protocol '{protocol_id}' was not found."
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
    ) -> ProtocolTemplate:
        protocol = ProtocolService.get_protocol(
            db,
            protocol_id,
        )

        return ProtocolRepository.deactivate(
            db,
            protocol,
        )