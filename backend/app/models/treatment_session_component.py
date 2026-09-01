from __future__ import annotations

import uuid
from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
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
    from backend.app.models.treatment_component import (
        TreatmentComponent,
    )
    from backend.app.models.treatment_session import (
        TreatmentSession,
    )


class TreatmentSessionComponent(Base):
    __tablename__ = "treatment_session_components"

    __table_args__ = (
        UniqueConstraint(
            "treatment_session_id",
            "sequence",
            name=(
                "uq_treatment_session_components_"
                "session_sequence"
            ),
        ),
        CheckConstraint(
            (
                "actual_amount IS NULL "
                "OR actual_amount > 0"
            ),
            name=(
                "ck_treatment_session_components_"
                "positive_amount"
            ),
        ),
        CheckConstraint(
            "sequence >= 1",
            name=(
                "ck_treatment_session_components_"
                "positive_sequence"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    treatment_session_id: Mapped[
        str
    ] = mapped_column(
        String(36),
        ForeignKey(
            "treatment_sessions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    treatment_component_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        ForeignKey(
            "treatment_components.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
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

    actual_amount: Mapped[
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
    )

    source: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    manufacturer: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    product_name: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    lot_number: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    batch_number: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    expiry_date: Mapped[
        date | None
    ] = mapped_column(
        Date,
        nullable=True,
    )

    concentration: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    preparation_method: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    activation_method: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    storage_condition: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    preparation_parameters: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(
            timezone.utc
        ),
    )

    updated_at: Mapped[
        datetime
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(
            timezone.utc
        ),
        onupdate=lambda: datetime.now(
            timezone.utc
        ),
    )

    treatment_session: Mapped[
        "TreatmentSession"
    ] = relationship(
        back_populates="components",
    )

    treatment_component: Mapped[
        "TreatmentComponent | None"
    ] = relationship(
        back_populates="session_components",
    )

    material: Mapped[
        "OrthobiologicMaterial"
    ] = relationship(
        back_populates="session_components",
    )
