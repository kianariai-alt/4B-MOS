"""Immutable treatment outcome observations for longitudinal learning."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class TreatmentOutcome(Base):
    __tablename__ = "treatment_outcomes"
    __table_args__ = (
        CheckConstraint(
            "follow_up_day >= 0",
            name="ck_treatment_outcome_follow_up_day",
        ),
        CheckConstraint(
            "outcome_status IN "
            "('improved', 'unchanged', 'worsened', 'mixed', 'unknown')",
            name="ck_treatment_outcome_status",
        ),
        CheckConstraint(
            "patient_rating IS NULL OR "
            "(patient_rating >= 1 AND patient_rating <= 5)",
            name="ck_treatment_outcome_patient_rating",
        ),
        CheckConstraint(
            "physician_rating IS NULL OR "
            "(physician_rating >= 1 AND physician_rating <= 5)",
            name="ck_treatment_outcome_physician_rating",
        ),
        CheckConstraint(
            "pain_score IS NULL OR "
            "(pain_score >= 0 AND pain_score <= 10)",
            name="ck_treatment_outcome_pain_score",
        ),
        CheckConstraint(
            "function_score IS NULL OR "
            "(function_score >= 0 AND function_score <= 100)",
            name="ck_treatment_outcome_function_score",
        ),
        CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_treatment_outcome_context_sha256",
        ),
        CheckConstraint(
            "length(treatment_snapshot_sha256) = 64",
            name="ck_treatment_outcome_treatment_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_treatment_outcome_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    treatment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("treatments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    visit_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    treatment_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    protocol_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    protocol_version: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
    )
    body_region: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    clinical_context_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    treatment_snapshot_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    finalization_sha256s: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    follow_up_day: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    outcome_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    patient_rating: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    physician_rating: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    pain_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    function_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    outcome_measures: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    adverse_events: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


def _reject_outcome_rewrite(mapper, connection, target):
    raise ValueError(
        "Treatment outcomes cannot be updated or deleted through the ORM. "
        "Record a new follow-up observation instead."
    )


event.listen(TreatmentOutcome, "before_update", _reject_outcome_rewrite)
event.listen(TreatmentOutcome, "before_delete", _reject_outcome_rewrite)
