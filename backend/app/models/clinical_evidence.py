"""Immutable, clinician-selected evidence briefs for one visit snapshot."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    JSON,
    String,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ClinicalEvidenceBrief(Base):
    __tablename__ = "clinical_evidence_briefs"
    __table_args__ = (
        CheckConstraint(
            "selection_method = 'clinician_selected'",
            name="ck_clinical_evidence_brief_selection_method",
        ),
        CheckConstraint(
            "output_type = 'evidence_summary'",
            name="ck_clinical_evidence_brief_output_type",
        ),
        CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_clinical_evidence_brief_context_sha256",
        ),
        CheckConstraint(
            "length(knowledge_set_sha256) = 64",
            name="ck_clinical_evidence_brief_knowledge_sha256",
        ),
        CheckConstraint(
            "length(sha256) = 64",
            name="ck_clinical_evidence_brief_sha256",
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
    intake_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clinical_intakes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    report_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    clinical_context_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    knowledge_fact_ids: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    knowledge_set_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    knowledge_as_of: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    selection_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="clinician_selected",
    )
    output_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="evidence_summary",
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


def _reject_evidence_brief_rewrite(mapper, connection, target):
    raise ValueError(
        "Clinical evidence briefs cannot be updated or deleted through the ORM. "
        "Create a new brief for changed context or evidence."
    )


event.listen(
    ClinicalEvidenceBrief,
    "before_update",
    _reject_evidence_brief_rewrite,
)
event.listen(
    ClinicalEvidenceBrief,
    "before_delete",
    _reject_evidence_brief_rewrite,
)
