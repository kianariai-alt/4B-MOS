"""Append-only protocol learning governance records."""
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


class ProtocolGovernanceCase(Base):
    __tablename__ = "protocol_governance_cases"
    __table_args__ = (
        CheckConstraint(
            "case_type IN ("
            "'collect_more_data', 'monitor_no_change', "
            "'revision_candidate', 'deactivation_candidate'"
            ")",
            name="ck_protocol_governance_case_type",
        ),
        CheckConstraint(
            "length(source_learning_review_sha256) = 64",
            name="ck_protocol_governance_learning_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_case_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    protocol_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    protocol_version: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    treatment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    case_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_learning_review_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    learning_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    proposed_protocol: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_needed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )


class ProtocolGovernanceReview(Base):
    __tablename__ = "protocol_governance_reviews"
    __table_args__ = (
        CheckConstraint(
            "action IN ("
            "'clinical_approve', 'clinical_reject', 'request_changes', "
            "'operational_acknowledge', 'operational_hold'"
            ")",
            name="ck_protocol_governance_review_action",
        ),
        CheckConstraint("length(case_sha256) = 64", name="ck_protocol_governance_review_case_sha256"),
        CheckConstraint("length(sha256) = 64", name="ck_protocol_governance_review_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("protocol_governance_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    case_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )


def _reject_rewrite(mapper, connection, target):
    raise ValueError("Protocol governance records are append-only.")


for _model in (ProtocolGovernanceCase, ProtocolGovernanceReview):
    event.listen(_model, "before_update", _reject_rewrite)
    event.listen(_model, "before_delete", _reject_rewrite)
