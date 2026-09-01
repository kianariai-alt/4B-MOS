from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


if TYPE_CHECKING:
    from backend.app.models.protocol import ProtocolTemplate
    from backend.app.models.treatment_component import TreatmentComponent
    from backend.app.models.treatment_session import TreatmentSession
    from backend.app.models.visit import Visit


class Treatment(Base):
    __tablename__ = "treatments"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    visit_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "visits.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    protocol_template_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "protocol_templates.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    treatment_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="planned",
    )

    session_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    body_region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    protocol_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    protocol_version: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    protocol_snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    execution_parameters: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    dose_or_volume: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    performed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    visit: Mapped["Visit"] = relationship(
        back_populates="treatments",
    )

    protocol_template: Mapped["ProtocolTemplate | None"] = relationship()

    components: Mapped[list["TreatmentComponent"]] = relationship(
        back_populates="treatment",
        cascade="all, delete-orphan",
        order_by="TreatmentComponent.sequence",
    )

    sessions: Mapped[list["TreatmentSession"]] = relationship(
        back_populates="treatment",
        cascade="all, delete-orphan",
        order_by="TreatmentSession.session_number",
    )