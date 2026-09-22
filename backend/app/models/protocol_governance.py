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
    UniqueConstraint,
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
            "'revision_candidate', 'deactivation_candidate', "
            "'reactivation_candidate', 'rollback_revision_candidate'"
            ")",
            name="ck_protocol_governance_case_type",
        ),
        CheckConstraint(
            "length(source_learning_review_sha256) = 64",
            name="ck_protocol_governance_learning_sha256",
        ),
        CheckConstraint(
            "source_release_sha256 IS NULL OR length(source_release_sha256) = 64",
            name="ck_protocol_governance_source_release_sha256",
        ),
        CheckConstraint(
            "("
            "case_type IN ('reactivation_candidate', 'rollback_revision_candidate') "
            "AND source_release_id IS NOT NULL "
            "AND source_release_sha256 IS NOT NULL "
            "AND recovery_snapshot IS NOT NULL"
            ") OR ("
            "case_type NOT IN ('reactivation_candidate', 'rollback_revision_candidate') "
            "AND source_release_id IS NULL "
            "AND source_release_sha256 IS NULL "
            "AND recovery_snapshot IS NULL"
            ")",
            name="ck_protocol_governance_recovery_case_fields",
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
    source_release_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    source_release_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    recovery_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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




class ProtocolGovernanceRelease(Base):
    __tablename__ = "protocol_governance_releases"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            name="uq_protocol_governance_release_case",
        ),
        CheckConstraint(
            "action IN ('publish_revision', 'deactivate')",
            name="ck_protocol_governance_release_action",
        ),
        CheckConstraint(
            "length(case_sha256) = 64",
            name="ck_protocol_governance_release_case_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_release_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("protocol_governance_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    case_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_protocol_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("protocol_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    released_protocol_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("protocol_templates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_protocol_before: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_protocol_after: Mapped[dict] = mapped_column(JSON, nullable=False)
    released_protocol_snapshot: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    executed_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_note: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )




class ProtocolGovernanceRecovery(Base):
    __tablename__ = "protocol_governance_recoveries"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            name="uq_protocol_governance_recovery_case",
        ),
        UniqueConstraint(
            "source_release_id",
            name="uq_protocol_governance_recovery_source_release",
        ),
        CheckConstraint(
            "action IN ('reactivate', 'rollback_revision')",
            name="ck_protocol_governance_recovery_action",
        ),
        CheckConstraint(
            "length(case_sha256) = 64",
            name="ck_protocol_governance_recovery_case_sha256",
        ),
        CheckConstraint(
            "length(source_release_sha256) = 64",
            name="ck_protocol_governance_recovery_release_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_recovery_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("protocol_governance_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    case_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_release_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("protocol_governance_releases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_release_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    deactivated_protocol_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("protocol_templates.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reactivated_protocol_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("protocol_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    before_snapshots: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_snapshots: Mapped[dict] = mapped_column(JSON, nullable=False)
    executed_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_note: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

def _reject_rewrite(mapper, connection, target):
    raise ValueError("Protocol governance records are append-only.")


for _model in (
    ProtocolGovernanceCase,
    ProtocolGovernanceReview,
    ProtocolGovernanceRelease,
    ProtocolGovernanceRecovery,
):
    event.listen(_model, "before_update", _reject_rewrite)
    event.listen(_model, "before_delete", _reject_rewrite)
