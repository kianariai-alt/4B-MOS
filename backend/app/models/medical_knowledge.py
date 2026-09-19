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


class MedicalKnowledgeFact(Base):
    __tablename__ = "medical_knowledge_facts"
    __table_args__ = (
        UniqueConstraint(
            "fact_key",
            "version",
            name="uq_medical_knowledge_facts_key_version",
        ),
        UniqueConstraint(
            "supersedes_fact_id",
            name="uq_medical_knowledge_facts_supersedes",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_medical_knowledge_facts_version_positive",
        ),
        CheckConstraint(
            "row_version >= 1",
            name="ck_medical_knowledge_facts_row_version_positive",
        ),
        CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'retired')",
            name="ck_medical_knowledge_facts_status",
        ),
        CheckConstraint(
            "evidence_grade IN "
            "('high', 'moderate', 'low', 'very_low', 'consensus', 'ungraded')",
            name="ck_medical_knowledge_facts_evidence_grade",
        ),
        CheckConstraint(
            "therapy_type IS NULL OR therapy_type IN "
            "('PRP', 'PRGF', 'ACS', 'PL', 'SVF', 'EXOSOME', 'MSC')",
            name="ck_medical_knowledge_facts_therapy_type",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_medical_knowledge_facts_valid_dates",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    fact_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    title: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )
    statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    clinical_domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    therapy_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    population: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    indication: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    contraindications: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    evidence_grade: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        index=True,
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    supersedes_fact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "medical_knowledge_facts.id",
            ondelete="NO ACTION",
        ),
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
    review_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    valid_from: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    valid_to: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
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

    sources: Mapped[list[MedicalKnowledgeSource]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
        order_by="MedicalKnowledgeSource.sort_order",
        lazy="selectin",
    )

    __mapper_args__ = {
        "version_id_col": row_version,
    }


class MedicalKnowledgeSource(Base):
    __tablename__ = "medical_knowledge_sources"
    __table_args__ = (
        UniqueConstraint(
            "fact_id",
            "sort_order",
            name="uq_medical_knowledge_sources_fact_order",
        ),
        CheckConstraint(
            "sort_order >= 1",
            name="ck_medical_knowledge_sources_order_positive",
        ),
        CheckConstraint(
            "source_type IN "
            "('guideline', 'systematic_review', 'randomized_trial', "
            "'observational_study', 'regulatory', 'consensus', "
            "'textbook', 'other')",
            name="ck_medical_knowledge_sources_type",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    fact_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "medical_knowledge_facts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    citation: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    publisher: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    url: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    doi: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    publication_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )
    guideline_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    accessed_at: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        default=date.today,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    fact: Mapped[MedicalKnowledgeFact] = relationship(
        back_populates="sources",
    )
