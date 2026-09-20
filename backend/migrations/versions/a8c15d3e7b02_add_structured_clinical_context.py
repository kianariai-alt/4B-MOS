"""Add versioned structured intake and paraclinical context.

Revision ID: a8c15d3e7b02
Revises: f4b14c2d9a01
"""

from alembic import context, op
import sqlalchemy as sa


revision = "a8c15d3e7b02"
down_revision = "f4b14c2d9a01"
branch_labels = None
depends_on = None


def _state_metadata_constraint() -> str:
    return (
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
        "AND entered_in_error_at IS NOT NULL AND error_reason IS NOT NULL)"
    )


def upgrade():
    op.create_table(
        "clinical_intakes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("chief_complaint", sa.Text(), nullable=False),
        sa.Column("history_present_illness", sa.Text(), nullable=False),
        sa.Column("body_region", sa.String(100), nullable=True),
        sa.Column("laterality", sa.String(30), nullable=True),
        sa.Column("symptom_onset_date", sa.Date(), nullable=True),
        sa.Column("pain_score", sa.Integer(), nullable=True),
        sa.Column(
            "functional_limitations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "relevant_history",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "current_medications",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "allergies",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("exam_findings", sa.Text(), nullable=True),
        sa.Column(
            "red_flags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("clinical_impression", sa.Text(), nullable=True),
        sa.Column("care_goal", sa.Text(), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("supersedes_intake_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("finalized_by_user_id", sa.String(36), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entered_in_error_by_user_id", sa.String(36), nullable=True),
        sa.Column("entered_in_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_clinical_intake_version"),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_clinical_intake_row_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'final', 'superseded', 'entered_in_error')",
            name="ck_clinical_intake_status",
        ),
        sa.CheckConstraint(
            "laterality IS NULL OR laterality IN "
            "('left', 'right', 'bilateral', 'midline', 'not_applicable', 'unknown')",
            name="ck_clinical_intake_laterality",
        ),
        sa.CheckConstraint(
            "pain_score IS NULL OR (pain_score >= 0 AND pain_score <= 10)",
            name="ck_clinical_intake_pain_score",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_clinical_intake_sha256",
        ),
        sa.CheckConstraint(
            "(supersedes_intake_id IS NULL AND revision_reason IS NULL) OR "
            "(supersedes_intake_id IS NOT NULL AND revision_reason IS NOT NULL)",
            name="ck_clinical_intake_revision_reason",
        ),
        sa.CheckConstraint(
            _state_metadata_constraint(),
            name="ck_clinical_intake_state_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_intake_id"],
            ["clinical_intakes.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entered_in_error_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "visit_id",
            "version",
            name="uq_clinical_intake_visit_version",
        ),
        sa.UniqueConstraint(
            "supersedes_intake_id",
            name="uq_clinical_intake_supersedes",
        ),
    )
    op.create_index(
        "ix_clinical_intakes_visit_id",
        "clinical_intakes",
        ["visit_id"],
        unique=False,
    )
    op.create_index(
        "ix_clinical_intakes_status",
        "clinical_intakes",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_clinical_intakes_supersedes_intake_id",
        "clinical_intakes",
        ["supersedes_intake_id"],
        unique=False,
    )
    op.create_index(
        "ix_clinical_intakes_created_by_user_id",
        "clinical_intakes",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_clinical_intakes_finalized_by_user_id",
        "clinical_intakes",
        ["finalized_by_user_id"],
        unique=False,
    )

    op.create_table(
        "paraclinical_reports",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("report_key", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("external_identifier", sa.String(200), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performer", sa.String(300), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.String(1000), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("supersedes_report_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("finalized_by_user_id", sa.String(36), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entered_in_error_by_user_id", sa.String(36), nullable=True),
        sa.Column("entered_in_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=True),
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_paraclinical_report_version"),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_paraclinical_report_row_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'final', 'superseded', 'entered_in_error')",
            name="ck_paraclinical_report_status",
        ),
        sa.CheckConstraint(
            "category IN ('laboratory', 'imaging', 'pathology', "
            "'vital_sign', 'clinical_test', 'other')",
            name="ck_paraclinical_report_category",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_paraclinical_report_sha256",
        ),
        sa.CheckConstraint(
            "(supersedes_report_id IS NULL AND revision_reason IS NULL) OR "
            "(supersedes_report_id IS NOT NULL AND revision_reason IS NOT NULL)",
            name="ck_paraclinical_report_revision_reason",
        ),
        sa.CheckConstraint(
            _state_metadata_constraint(),
            name="ck_paraclinical_report_state_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_report_id"],
            ["paraclinical_reports.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entered_in_error_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "visit_id",
            "report_key",
            "version",
            name="uq_paraclinical_report_key_version",
        ),
        sa.UniqueConstraint(
            "supersedes_report_id",
            name="uq_paraclinical_report_supersedes",
        ),
    )
    for index_name, columns in (
        ("ix_paraclinical_reports_visit_id", ["visit_id"]),
        ("ix_paraclinical_reports_report_key", ["report_key"]),
        ("ix_paraclinical_reports_status", ["status"]),
        ("ix_paraclinical_reports_category", ["category"]),
        ("ix_paraclinical_reports_supersedes_report_id", ["supersedes_report_id"]),
        ("ix_paraclinical_reports_created_by_user_id", ["created_by_user_id"]),
    ):
        op.create_index(
            index_name,
            "paraclinical_reports",
            columns,
            unique=False,
        )

    op.create_table(
        "paraclinical_observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("code_system", sa.String(30), nullable=False),
        sa.Column("code_system_uri", sa.String(500), nullable=True),
        sa.Column("code_system_version", sa.String(50), nullable=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("value_type", sa.String(30), nullable=False),
        sa.Column("quantity_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("string_value", sa.Text(), nullable=True),
        sa.Column("boolean_value", sa.Boolean(), nullable=True),
        sa.Column("integer_value", sa.Integer(), nullable=True),
        sa.Column("coded_value", sa.String(100), nullable=True),
        sa.Column("coded_system", sa.String(100), nullable=True),
        sa.Column("coded_display", sa.String(300), nullable=True),
        sa.Column("datetime_value", sa.DateTime(timezone=True), nullable=True),
        sa.Column("absent_reason", sa.String(100), nullable=True),
        sa.Column("unit_code", sa.String(100), nullable=True),
        sa.Column("unit_display", sa.String(100), nullable=True),
        sa.Column("reference_low", sa.Numeric(18, 6), nullable=True),
        sa.Column("reference_high", sa.Numeric(18, 6), nullable=True),
        sa.Column("reference_text", sa.Text(), nullable=True),
        sa.Column("interpretation", sa.String(30), nullable=True),
        sa.Column("body_site", sa.String(200), nullable=True),
        sa.Column("specimen", sa.String(200), nullable=True),
        sa.Column("method", sa.String(300), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_paraclinical_observation_order",
        ),
        sa.CheckConstraint(
            "category IN ('laboratory', 'imaging', 'pathology', "
            "'vital_sign', 'clinical_test', 'other')",
            name="ck_paraclinical_observation_category",
        ),
        sa.CheckConstraint(
            "code_system IN ('LOINC', 'SNOMED_CT', 'LOCAL', 'OTHER')",
            name="ck_paraclinical_observation_code_system",
        ),
        sa.CheckConstraint(
            "code_system != 'OTHER' OR "
            "(code_system_uri IS NOT NULL AND length(trim(code_system_uri)) > 0)",
            name="ck_paraclinical_observation_other_system",
        ),
        sa.CheckConstraint(
            "value_type IN ('quantity', 'string', 'boolean', 'integer', "
            "'coded', 'datetime', 'absent')",
            name="ck_paraclinical_observation_value_type",
        ),
        sa.CheckConstraint(
            "interpretation IS NULL OR interpretation IN "
            "('normal', 'low', 'high', 'critical_low', 'critical_high', "
            "'abnormal', 'indeterminate')",
            name="ck_paraclinical_observation_interpretation",
        ),
        sa.CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL "
            "OR reference_high >= reference_low",
            name="ck_paraclinical_observation_reference",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "value_type = 'quantity' OR "
            "(unit_code IS NULL AND unit_display IS NULL "
            "AND reference_low IS NULL AND reference_high IS NULL)",
            name="ck_paraclinical_observation_quantity_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["paraclinical_reports.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_id",
            "sort_order",
            name="uq_paraclinical_observation_order",
        ),
    )
    op.create_index(
        "ix_paraclinical_observations_report_id",
        "paraclinical_observations",
        ["report_id"],
        unique=False,
    )


def downgrade():
    # These tables hold patient-specific clinical documentation. A routine
    # rollback must never erase it, regardless of draft/final/error status.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: clinical context cannot be checked."
        )
    connection = op.get_bind()
    counts = {
        table: connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in (
            "clinical_intakes",
            "paraclinical_reports",
            "paraclinical_observations",
        )
    }
    if any(counts.values()):
        raise RuntimeError(
            "Downgrade refused: structured clinical context contains data."
        )
    op.drop_index(
        "ix_paraclinical_observations_report_id",
        table_name="paraclinical_observations",
    )
    op.drop_table("paraclinical_observations")
    for index_name in (
        "ix_paraclinical_reports_created_by_user_id",
        "ix_paraclinical_reports_supersedes_report_id",
        "ix_paraclinical_reports_category",
        "ix_paraclinical_reports_status",
        "ix_paraclinical_reports_report_key",
        "ix_paraclinical_reports_visit_id",
    ):
        op.drop_index(index_name, table_name="paraclinical_reports")
    op.drop_table("paraclinical_reports")
    for index_name in (
        "ix_clinical_intakes_finalized_by_user_id",
        "ix_clinical_intakes_created_by_user_id",
        "ix_clinical_intakes_supersedes_intake_id",
        "ix_clinical_intakes_status",
        "ix_clinical_intakes_visit_id",
    ):
        op.drop_index(index_name, table_name="clinical_intakes")
    op.drop_table("clinical_intakes")
