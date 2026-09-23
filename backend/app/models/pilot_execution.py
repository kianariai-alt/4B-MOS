"""Append-only enrollment and stop evidence for the controlled pilot.

Pilot enrollment never constitutes permission to treat an individual patient.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class PilotVisitEnrollment(Base):
    __tablename__ = "pilot_visit_enrollments"
    __table_args__ = (
        UniqueConstraint("visit_id", name="uq_pilot_visit_enrollment_visit"),
        CheckConstraint("length(release_decision_sha256) = 64", name="ck_pilot_enrollment_release_sha256"),
        CheckConstraint("length(clinician_decision_sha256) = 64", name="ck_pilot_enrollment_clinician_sha256"),
        CheckConstraint("length(protocol_snapshot_sha256) = 64", name="ck_pilot_enrollment_protocol_sha256"),
        CheckConstraint("length(sha256) = 64", name="ck_pilot_enrollment_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    release_decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pilot_release_decisions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    release_decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    visit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    protocol_template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("protocol_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    protocol_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    clinician_decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("treatment_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinician_decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    consent_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    clinician_statement: Mapped[str] = mapped_column(Text, nullable=False)
    enrolled_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )


class PilotStopEvent(Base):
    __tablename__ = "pilot_stop_events"
    __table_args__ = (
        UniqueConstraint("release_decision_id", name="uq_pilot_stop_decision"),
        CheckConstraint(
            "reason_category IN ('clinical_safety', 'operational', 'privacy', 'other')",
            name="ck_pilot_stop_reason_category",
        ),
        CheckConstraint("length(release_decision_sha256) = 64", name="ck_pilot_stop_release_sha256"),
        CheckConstraint("length(sha256) = 64", name="ck_pilot_stop_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    release_decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pilot_release_decisions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    release_decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_category: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    stopped_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), index=True,
    )


def _reject_rewrite(mapper, connection, target):
    raise ValueError("Pilot execution evidence is append-only; create a new release for restart.")


for _model in (PilotVisitEnrollment, PilotStopEvent):
    event.listen(_model, "before_update", _reject_rewrite)
    event.listen(_model, "before_delete", _reject_rewrite)
