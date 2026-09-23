"""Immutable manual gate attestations and independent reviews."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


GATE_NAMES = (
    "clinical_protocol_signoff",
    "clinical_safety_signoff",
    "backup_restore",
    "security_perimeter",
    "monitoring_alerting",
    "human_ui_acceptance",
    "privacy_retention_legal",
)


class PilotManualGateAttestation(Base):
    __tablename__ = "pilot_manual_gate_attestations"
    __table_args__ = (
        CheckConstraint(
            "gate_name IN ("
            "'clinical_protocol_signoff', 'clinical_safety_signoff', "
            "'backup_restore', 'security_perimeter', 'monitoring_alerting', "
            "'human_ui_acceptance', 'privacy_retention_legal'"
            ")",
            name="ck_pilot_manual_gate_attestation_name",
        ),
        CheckConstraint(
            "length(readiness_sha256) = 64",
            name="ck_pilot_manual_gate_attestation_readiness_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_manual_gate_attestation_sha256",
        ),
        UniqueConstraint(
            "supersedes_attestation_id",
            name="uq_pilot_manual_gate_attestation_supersedes",
        ),
        UniqueConstraint(
            "gate_name",
            "generation",
            name="uq_pilot_manual_gate_attestation_generation",
        ),
        CheckConstraint(
            "generation >= 1",
            name="ck_pilot_manual_gate_attestation_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    gate_name: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        index=True,
    )
    readiness_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    release_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_attestation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "pilot_manual_gate_attestations.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    attested_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attested_by_role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class PilotManualGateReview(Base):
    __tablename__ = "pilot_manual_gate_reviews"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id",
            name="uq_pilot_manual_gate_review_attestation",
        ),
        CheckConstraint(
            "action IN ('approve', 'reject')",
            name="ck_pilot_manual_gate_review_action",
        ),
        CheckConstraint(
            "length(attestation_sha256) = 64",
            name="ck_pilot_manual_gate_review_attestation_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_manual_gate_review_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    attestation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "pilot_manual_gate_attestations.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    attestation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reviewed_by_role: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


def _reject_rewrite(mapper, connection, target):
    raise ValueError("Pilot manual gate records are append-only.")


for _model in (PilotManualGateAttestation, PilotManualGateReview):
    event.listen(_model, "before_update", _reject_rewrite)
    event.listen(_model, "before_delete", _reject_rewrite)
