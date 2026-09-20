from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class ClinicalIntake(Base):
    __tablename__ = "clinical_intakes"
    __table_args__ = (
        UniqueConstraint(
            "visit_id",
            "version",
            name="uq_clinical_intake_visit_version",
        ),
        UniqueConstraint(
            "supersedes_intake_id",
            name="uq_clinical_intake_supersedes",
        ),
        CheckConstraint("version >= 1", name="ck_clinical_intake_version"),
        CheckConstraint("row_version >= 1", name="ck_clinical_intake_row_version"),
        CheckConstraint(
            "status IN ('draft', 'final', 'superseded', 'entered_in_error')",
            name="ck_clinical_intake_status",
        ),
        CheckConstraint(
            "laterality IS NULL OR laterality IN "
            "('left', 'right', 'bilateral', 'midline', 'not_applicable', 'unknown')",
            name="ck_clinical_intake_laterality",
        ),
        CheckConstraint(
            "pain_score IS NULL OR (pain_score >= 0 AND pain_score <= 10)",
            name="ck_clinical_intake_pain_score",
        ),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_clinical_intake_sha256",
        ),
        CheckConstraint(
            "(supersedes_intake_id IS NULL AND revision_reason IS NULL) OR "
            "(supersedes_intake_id IS NOT NULL AND revision_reason IS NOT NULL)",
            name="ck_clinical_intake_revision_reason",
        ),
        CheckConstraint(
            "(status = 'draft' AND finalized_by_user_id IS NULL "
            "AND finalized_at IS NULL AND entered_in_error_by_user_id IS NULL "
            "AND entered_in_error_at IS NULL AND error_reason IS NULL) OR "
            "(status IN ('final', 'superseded') "
            "AND finalized_by_user_id IS NOT NULL AND finalized_at IS NOT NULL "
            "AND entered_in_error_by_user_id IS NULL "
            "AND entered_in_error_at IS NULL AND error_reason IS NULL) OR "
            "(status = 'entered_in_error' "
            "AND finalized_by_user_id IS NOT NULL AND finalized_at IS NOT NULL "
            "AND entered_in_error_by_user_id IS NOT NULL "
            "AND entered_in_error_at IS NOT NULL AND error_reason IS NOT NULL)",
            name="ck_clinical_intake_state_metadata",
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
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        index=True,
    )
    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    history_present_illness: Mapped[str] = mapped_column(Text, nullable=False)
    body_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    laterality: Mapped[str | None] = mapped_column(String(30), nullable=True)
    symptom_onset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pain_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    functional_limitations: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    relevant_history: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    current_medications: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    allergies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exam_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    red_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    clinical_impression: Mapped[str | None] = mapped_column(Text, nullable=True)
    care_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_intake_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("clinical_intakes.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    finalized_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    entered_in_error_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    entered_in_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    __mapper_args__ = {"version_id_col": row_version}


class ParaclinicalReport(Base):
    __tablename__ = "paraclinical_reports"
    __table_args__ = (
        UniqueConstraint(
            "visit_id",
            "report_key",
            "version",
            name="uq_paraclinical_report_key_version",
        ),
        UniqueConstraint(
            "supersedes_report_id",
            name="uq_paraclinical_report_supersedes",
        ),
        CheckConstraint("version >= 1", name="ck_paraclinical_report_version"),
        CheckConstraint("row_version >= 1", name="ck_paraclinical_report_row_version"),
        CheckConstraint(
            "status IN ('draft', 'final', 'superseded', 'entered_in_error')",
            name="ck_paraclinical_report_status",
        ),
        CheckConstraint(
            "category IN ('laboratory', 'imaging', 'pathology', "
            "'vital_sign', 'clinical_test', 'other')",
            name="ck_paraclinical_report_category",
        ),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_paraclinical_report_sha256",
        ),
        CheckConstraint(
            "(supersedes_report_id IS NULL AND revision_reason IS NULL) OR "
            "(supersedes_report_id IS NOT NULL AND revision_reason IS NOT NULL)",
            name="ck_paraclinical_report_revision_reason",
        ),
        CheckConstraint(
            "(status = 'draft' AND finalized_by_user_id IS NULL "
            "AND finalized_at IS NULL AND entered_in_error_by_user_id IS NULL "
            "AND entered_in_error_at IS NULL AND error_reason IS NULL) OR "
            "(status IN ('final', 'superseded') "
            "AND finalized_by_user_id IS NOT NULL AND finalized_at IS NOT NULL "
            "AND entered_in_error_by_user_id IS NULL "
            "AND entered_in_error_at IS NULL AND error_reason IS NULL) OR "
            "(status = 'entered_in_error' "
            "AND finalized_by_user_id IS NOT NULL AND finalized_at IS NOT NULL "
            "AND entered_in_error_by_user_id IS NOT NULL "
            "AND entered_in_error_at IS NOT NULL AND error_reason IS NOT NULL)",
            name="ck_paraclinical_report_state_metadata",
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
    report_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        index=True,
    )
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    external_identifier: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    performed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    performer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    revision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_report_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("paraclinical_reports.id", ondelete="NO ACTION"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    finalized_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    entered_in_error_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    entered_in_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    observations: Mapped[list[ParaclinicalObservation]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ParaclinicalObservation.sort_order",
        lazy="selectin",
    )

    __mapper_args__ = {"version_id_col": row_version}


class ParaclinicalObservation(Base):
    __tablename__ = "paraclinical_observations"
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "sort_order",
            name="uq_paraclinical_observation_order",
        ),
        CheckConstraint("sort_order >= 1", name="ck_paraclinical_observation_order"),
        CheckConstraint(
            "category IN ('laboratory', 'imaging', 'pathology', "
            "'vital_sign', 'clinical_test', 'other')",
            name="ck_paraclinical_observation_category",
        ),
        CheckConstraint(
            "code_system IN ('LOINC', 'SNOMED_CT', 'LOCAL', 'OTHER')",
            name="ck_paraclinical_observation_code_system",
        ),
        CheckConstraint(
            "code_system != 'OTHER' OR "
            "(code_system_uri IS NOT NULL AND length(trim(code_system_uri)) > 0)",
            name="ck_paraclinical_observation_other_system",
        ),
        CheckConstraint(
            "value_type IN ('quantity', 'string', 'boolean', 'integer', "
            "'coded', 'datetime', 'absent')",
            name="ck_paraclinical_observation_value_type",
        ),
        CheckConstraint(
            "interpretation IS NULL OR interpretation IN "
            "('normal', 'low', 'high', 'critical_low', 'critical_high', "
            "'abnormal', 'indeterminate')",
            name="ck_paraclinical_observation_interpretation",
        ),
        CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL "
            "OR reference_high >= reference_low",
            name="ck_paraclinical_observation_reference",
        ),
        CheckConstraint(
            "(value_type = 'quantity' AND quantity_value IS NOT NULL "
            "AND unit_code IS NOT NULL AND string_value IS NULL "
            "AND boolean_value IS NULL AND integer_value IS NULL "
            "AND coded_value IS NULL AND coded_system IS NULL "
            "AND coded_display IS NULL AND datetime_value IS NULL "
            "AND absent_reason IS NULL) OR "
            "(value_type = 'string' AND string_value IS NOT NULL "
            "AND quantity_value IS NULL AND boolean_value IS NULL "
            "AND integer_value IS NULL AND coded_value IS NULL "
            "AND coded_system IS NULL AND coded_display IS NULL "
            "AND datetime_value IS NULL AND absent_reason IS NULL) OR "
            "(value_type = 'boolean' AND boolean_value IS NOT NULL "
            "AND quantity_value IS NULL AND string_value IS NULL "
            "AND integer_value IS NULL AND coded_value IS NULL "
            "AND coded_system IS NULL AND coded_display IS NULL "
            "AND datetime_value IS NULL AND absent_reason IS NULL) OR "
            "(value_type = 'integer' AND integer_value IS NOT NULL "
            "AND quantity_value IS NULL AND string_value IS NULL "
            "AND boolean_value IS NULL AND coded_value IS NULL "
            "AND coded_system IS NULL AND coded_display IS NULL "
            "AND datetime_value IS NULL AND absent_reason IS NULL) OR "
            "(value_type = 'coded' AND coded_value IS NOT NULL "
            "AND coded_system IS NOT NULL AND quantity_value IS NULL "
            "AND string_value IS NULL AND boolean_value IS NULL "
            "AND integer_value IS NULL AND datetime_value IS NULL "
            "AND absent_reason IS NULL) OR "
            "(value_type = 'datetime' AND datetime_value IS NOT NULL "
            "AND quantity_value IS NULL AND string_value IS NULL "
            "AND boolean_value IS NULL AND integer_value IS NULL "
            "AND coded_value IS NULL AND coded_system IS NULL "
            "AND coded_display IS NULL AND absent_reason IS NULL) OR "
            "(value_type = 'absent' AND absent_reason IS NOT NULL "
            "AND quantity_value IS NULL AND string_value IS NULL "
            "AND boolean_value IS NULL AND integer_value IS NULL "
            "AND coded_value IS NULL AND coded_system IS NULL "
            "AND coded_display IS NULL AND datetime_value IS NULL)",
            name="ck_paraclinical_observation_value",
        ),
        CheckConstraint(
            "value_type = 'quantity' OR "
            "(unit_code IS NULL AND unit_display IS NULL "
            "AND reference_low IS NULL AND reference_high IS NULL)",
            name="ck_paraclinical_observation_quantity_metadata",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("paraclinical_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    code_system: Mapped[str] = mapped_column(String(30), nullable=False)
    code_system_uri: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    code_system_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    string_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    integer_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coded_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    coded_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    coded_display: Mapped[str | None] = mapped_column(String(300), nullable=True)
    datetime_value: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    absent_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_display: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_low: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    reference_high: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    reference_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    interpretation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    body_site: Mapped[str | None] = mapped_column(String(200), nullable=True)
    specimen: Mapped[str | None] = mapped_column(String(200), nullable=True)
    method: Mapped[str | None] = mapped_column(String(300), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    report: Mapped[ParaclinicalReport] = relationship(
        back_populates="observations",
    )
