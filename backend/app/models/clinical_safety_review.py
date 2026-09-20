"""Append-only clinician review events for clinical-safety findings."""

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
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ClinicalSafetyFindingReview(Base):
    __tablename__ = "clinical_safety_finding_reviews"
    __table_args__ = (
        UniqueConstraint(
            "finding_id",
            "sequence",
            name="uq_clinical_safety_finding_review_sequence",
        ),
        CheckConstraint(
            "sequence >= 1",
            name="ck_clinical_safety_finding_review_sequence",
        ),
        CheckConstraint(
            "action IN ('acknowledged', 'escalated', 'assessed')",
            name="ck_clinical_safety_finding_review_action",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('requires_action', 'not_applicable', 'action_documented', "
            "'monitoring')",
            name="ck_clinical_safety_finding_review_disposition",
        ),
        CheckConstraint(
            "(action = 'assessed' AND disposition IS NOT NULL) OR "
            "(action != 'assessed' AND disposition IS NULL)",
            name="ck_clinical_safety_finding_review_action_disposition",
        ),
        CheckConstraint(
            "(sequence = 1 AND previous_review_sha256 IS NULL) OR "
            "(sequence > 1 AND previous_review_sha256 IS NOT NULL)",
            name="ck_clinical_safety_finding_review_chain",
        ),
        CheckConstraint(
            "previous_review_sha256 IS NULL OR "
            "length(previous_review_sha256) = 64",
            name="ck_clinical_safety_finding_review_previous_sha256",
        ),
        CheckConstraint(
            "length(evaluation_result_sha256) = 64",
            name="ck_clinical_safety_finding_review_evaluation_sha256",
        ),
        CheckConstraint(
            "length(rule_content_sha256) = 64",
            name="ck_clinical_safety_finding_review_rule_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_clinical_safety_finding_review_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    finding_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clinical_safety_findings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    disposition: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evaluation_result_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    rule_content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    previous_review_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


def _reject_finding_review_rewrite(mapper, connection, target):
    raise ValueError(
        "Clinical safety finding reviews cannot be updated or deleted through "
        "the ORM. Record a new evaluation for changed clinical context."
    )


event.listen(
    ClinicalSafetyFindingReview,
    "before_update",
    _reject_finding_review_rewrite,
)
event.listen(
    ClinicalSafetyFindingReview,
    "before_delete",
    _reject_finding_review_rewrite,
)
