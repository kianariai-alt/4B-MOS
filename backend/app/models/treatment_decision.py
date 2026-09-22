"""Append-only clinician decisions bound to a treatment-options roadmap."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class TreatmentDecision(Base):
    __tablename__ = "treatment_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision_type IN ("
            "'select_option', 'modify_option', 'combine_options', "
            "'choose_outside_roadmap', 'defer', 'no_treatment'"
            ")",
            name="ck_treatment_decision_type",
        ),
        CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_treatment_decision_context_sha256",
        ),
        CheckConstraint(
            "length(roadmap_sha256) = 64",
            name="ck_treatment_decision_roadmap_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_treatment_decision_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    visit_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    supersedes_decision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("treatment_decisions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    decision_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )
    clinical_context_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    roadmap_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    selected_protocols: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    modification_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    patient_preference_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    evidence_brief_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    decided_by_user_id: Mapped[str] = mapped_column(
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
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


def _reject_decision_rewrite(mapper, connection, target):
    raise ValueError(
        "Treatment decisions cannot be updated or deleted through the ORM. "
        "Record a superseding decision instead."
    )


event.listen(TreatmentDecision, "before_update", _reject_decision_rewrite)
event.listen(TreatmentDecision, "before_delete", _reject_decision_rewrite)
