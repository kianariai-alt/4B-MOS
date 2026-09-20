from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class ClinicalSafetyRule(Base):
    __tablename__ = "clinical_safety_rules"
    __table_args__ = (
        UniqueConstraint(
            "rule_key",
            "version",
            name="uq_clinical_safety_rule_key_version",
        ),
        UniqueConstraint(
            "supersedes_rule_id",
            name="uq_clinical_safety_rule_supersedes",
        ),
        CheckConstraint("version >= 1", name="ck_clinical_safety_rule_version"),
        CheckConstraint(
            "row_version >= 1",
            name="ck_clinical_safety_rule_row_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'retired')",
            name="ck_clinical_safety_rule_status",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'high', 'critical')",
            name="ck_clinical_safety_rule_severity",
        ),
        CheckConstraint(
            "action IN ('document', 'review_before_proceeding', "
            "'urgent_clinical_review')",
            name="ck_clinical_safety_rule_action",
        ),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_clinical_safety_rule_sha256",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_clinical_safety_rule_valid_dates",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    clinical_domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    predicate: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        index=True,
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_rule_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("clinical_safety_rules.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    knowledge_links: Mapped[list[ClinicalSafetyRuleKnowledge]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="ClinicalSafetyRuleKnowledge.sort_order",
        lazy="selectin",
    )

    __mapper_args__ = {"version_id_col": row_version}


class ClinicalSafetyRuleKnowledge(Base):
    __tablename__ = "clinical_safety_rule_knowledge"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "sort_order",
            name="uq_clinical_safety_rule_knowledge_order",
        ),
        UniqueConstraint(
            "rule_id",
            "medical_knowledge_fact_id",
            name="uq_clinical_safety_rule_knowledge_fact",
        ),
        CheckConstraint(
            "sort_order >= 1",
            name="ck_clinical_safety_rule_knowledge_order",
        ),
        CheckConstraint(
            "length(fact_content_sha256) = 64",
            name="ck_clinical_safety_rule_knowledge_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clinical_safety_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    medical_knowledge_fact_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("medical_knowledge_facts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fact_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    rule: Mapped[ClinicalSafetyRule] = relationship(back_populates="knowledge_links")


class ClinicalSafetyEvaluation(Base):
    __tablename__ = "clinical_safety_evaluations"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('alerts_present', 'no_alerts', 'no_active_rules')",
            name="ck_clinical_safety_evaluation_outcome",
        ),
        CheckConstraint(
            "evaluated_rule_count >= 0 AND triggered_count >= 0 "
            "AND triggered_count <= evaluated_rule_count",
            name="ck_clinical_safety_evaluation_counts",
        ),
        CheckConstraint(
            "highest_severity IS NULL OR highest_severity IN "
            "('info', 'warning', 'high', 'critical')",
            name="ck_clinical_safety_evaluation_severity",
        ),
        CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_clinical_safety_evaluation_context_sha256",
        ),
        CheckConstraint(
            "length(rule_set_sha256) = 64",
            name="ck_clinical_safety_evaluation_rule_set_sha256",
        ),
        CheckConstraint(
            "length(result_sha256) = 64",
            name="ck_clinical_safety_evaluation_result_sha256",
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
    intake_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("clinical_intakes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    report_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    engine_version: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    evaluated_rule_count: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_count: Mapped[int] = mapped_column(Integer, nullable=False)
    highest_severity: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    clinical_context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_set_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    findings: Mapped[list[ClinicalSafetyFinding]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="ClinicalSafetyFinding.sort_order",
        lazy="selectin",
    )


class ClinicalSafetyFinding(Base):
    __tablename__ = "clinical_safety_findings"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id",
            "sort_order",
            name="uq_clinical_safety_finding_order",
        ),
        UniqueConstraint(
            "evaluation_id",
            "rule_id",
            name="uq_clinical_safety_finding_rule",
        ),
        CheckConstraint(
            "sort_order >= 1",
            name="ck_clinical_safety_finding_order",
        ),
        CheckConstraint(
            "rule_version >= 1",
            name="ck_clinical_safety_finding_rule_version",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'high', 'critical')",
            name="ck_clinical_safety_finding_severity",
        ),
        CheckConstraint(
            "action IN ('document', 'review_before_proceeding', "
            "'urgent_clinical_review')",
            name="ck_clinical_safety_finding_action",
        ),
        CheckConstraint(
            "length(rule_content_sha256) = 64",
            name="ck_clinical_safety_finding_rule_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    evaluation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clinical_safety_evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clinical_safety_rules.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_fact_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    condition_trace: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    evaluation: Mapped[ClinicalSafetyEvaluation] = relationship(
        back_populates="findings"
    )
