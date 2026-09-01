from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from backend.app.db.base import Base


if TYPE_CHECKING:
    from backend.app.models.orthobiologic_material import (
        OrthobiologicMaterial,
    )
    from backend.app.models.treatment import Treatment


class TreatmentComponent(Base):
    __tablename__ = "treatment_components"

    __table_args__ = (
        UniqueConstraint(
            "treatment_id",
            "material_id",
            name=(
                "uq_treatment_components_"
                "treatment_material"
            ),
        ),
        UniqueConstraint(
            "treatment_id",
            "sequence",
            name=(
                "uq_treatment_components_"
                "treatment_sequence"
            ),
        ),
        CheckConstraint(
            (
                "planned_amount IS NULL "
                "OR planned_amount > 0"
            ),
            name=(
                "ck_treatment_components_"
                "positive_amount"
            ),
        ),
        CheckConstraint(
            "sequence >= 1",
            name=(
                "ck_treatment_components_"
                "positive_sequence"
            ),
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

    material_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "orthobiologic_materials.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    planned_amount: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(
            precision=12,
            scale=4,
        ),
        nullable=True,
    )

    unit: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(
            timezone.utc
        ),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(
            timezone.utc
        ),
        onupdate=lambda: datetime.now(
            timezone.utc
        ),
    )

    treatment: Mapped["Treatment"] = relationship(
        back_populates="components",
    )

    material: Mapped[
        "OrthobiologicMaterial"
    ] = relationship(
        back_populates="treatment_components",
    )
