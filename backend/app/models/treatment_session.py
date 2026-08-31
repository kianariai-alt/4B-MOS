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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


if TYPE_CHECKING:
    from backend.app.models.treatment import Treatment


class TreatmentSession(Base):
    __tablename__ = "treatment_sessions"

    __table_args__ = (
        UniqueConstraint(
            "treatment_id",
            "session_number",
            name="uq_treatment_sessions_treatment_number",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    treatment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "treatments.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    session_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="planned",
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    body_region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    dose_or_volume: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    execution_parameters: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    outcome_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    adverse_events: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
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

    treatment: Mapped["Treatment"] = relationship(
        back_populates="sessions",
    )