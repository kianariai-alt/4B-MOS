import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    patient_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "patients.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    visit_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="open",
    )

    chief_complaint: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    body_region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    diagnosis: Mapped[str | None] = mapped_column(
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

    patient = relationship(
        "Patient",
        back_populates="visits",
    )