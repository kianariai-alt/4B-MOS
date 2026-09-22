from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    JSON,
    String,
    Text,
    CheckConstraint,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ProtocolTemplate(Base):
    __tablename__ = "protocol_templates"

    __table_args__ = (
        UniqueConstraint(
            "code",
            "version",
            name="uq_protocol_templates_code_version",
        ),
        CheckConstraint(
            "source_governance_case_sha256 IS NULL OR "
            "length(source_governance_case_sha256) = 64",
            name="ck_protocol_template_governance_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    treatment_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    version: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="1.0",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    supersedes_protocol_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("protocol_templates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    source_governance_case_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("protocol_governance_cases.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    source_governance_case_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    preparation_parameters: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    administration_parameters: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    monitoring_parameters: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
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