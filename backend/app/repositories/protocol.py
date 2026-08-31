from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.protocol import ProtocolTemplate
from backend.app.schemas.protocol import ProtocolCreate


class ProtocolRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        protocol_id: str,
    ) -> ProtocolTemplate | None:
        return db.get(
            ProtocolTemplate,
            protocol_id,
        )

    @staticmethod
    def get_by_code_version(
        db: Session,
        code: str,
        version: str,
    ) -> ProtocolTemplate | None:
        statement = select(
            ProtocolTemplate
        ).where(
            ProtocolTemplate.code == code,
            ProtocolTemplate.version == version,
        )

        return db.scalar(statement)

    @staticmethod
    def list(
        db: Session,
        treatment_type: str | None = None,
    ) -> list[ProtocolTemplate]:
        statement = select(
            ProtocolTemplate
        ).order_by(
            ProtocolTemplate.code.asc(),
            ProtocolTemplate.version.asc(),
        )

        if treatment_type is not None:
            statement = statement.where(
                ProtocolTemplate.treatment_type == treatment_type
            )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def create(
        db: Session,
        payload: ProtocolCreate,
    ) -> ProtocolTemplate:
        protocol = ProtocolTemplate(
            **payload.model_dump(),
        )

        db.add(protocol)
        db.commit()
        db.refresh(protocol)

        return protocol

    @staticmethod
    def deactivate(
        db: Session,
        protocol: ProtocolTemplate,
    ) -> ProtocolTemplate:
        protocol.is_active = False

        db.add(protocol)
        db.commit()
        db.refresh(protocol)

        return protocol