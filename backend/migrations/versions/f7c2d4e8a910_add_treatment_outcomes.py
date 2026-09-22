"""Add immutable treatment outcome registry.

Revision ID: f7c2d4e8a910
Revises: e6b7c8d9a401
"""

from alembic import context, op
import sqlalchemy as sa


revision = "f7c2d4e8a910"
down_revision = "e6b7c8d9a401"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "treatment_outcomes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("treatment_id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("treatment_type", sa.String(50), nullable=False),
        sa.Column("protocol_code", sa.String(100), nullable=True),
        sa.Column("protocol_version", sa.String(30), nullable=True),
        sa.Column("body_region", sa.String(100), nullable=True),
        sa.Column("clinical_context_sha256", sa.String(64), nullable=False),
        sa.Column("treatment_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("finalization_sha256s", sa.JSON(), nullable=False),
        sa.Column("follow_up_day", sa.Integer(), nullable=False),
        sa.Column("outcome_status", sa.String(20), nullable=False),
        sa.Column("patient_rating", sa.Integer(), nullable=True),
        sa.Column("physician_rating", sa.Integer(), nullable=True),
        sa.Column("pain_score", sa.Integer(), nullable=True),
        sa.Column("function_score", sa.Integer(), nullable=True),
        sa.Column("outcome_measures", sa.JSON(), nullable=False),
        sa.Column("adverse_events", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "follow_up_day >= 0",
            name="ck_treatment_outcome_follow_up_day",
        ),
        sa.CheckConstraint(
            "outcome_status IN "
            "('improved', 'unchanged', 'worsened', 'mixed', 'unknown')",
            name="ck_treatment_outcome_status",
        ),
        sa.CheckConstraint(
            "patient_rating IS NULL OR "
            "(patient_rating >= 1 AND patient_rating <= 5)",
            name="ck_treatment_outcome_patient_rating",
        ),
        sa.CheckConstraint(
            "physician_rating IS NULL OR "
            "(physician_rating >= 1 AND physician_rating <= 5)",
            name="ck_treatment_outcome_physician_rating",
        ),
        sa.CheckConstraint(
            "pain_score IS NULL OR "
            "(pain_score >= 0 AND pain_score <= 10)",
            name="ck_treatment_outcome_pain_score",
        ),
        sa.CheckConstraint(
            "function_score IS NULL OR "
            "(function_score >= 0 AND function_score <= 100)",
            name="ck_treatment_outcome_function_score",
        ),
        sa.CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_treatment_outcome_context_sha256",
        ),
        sa.CheckConstraint(
            "length(treatment_snapshot_sha256) = 64",
            name="ck_treatment_outcome_treatment_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_treatment_outcome_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["treatment_id"],
            ["treatments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for index_name, columns in (
        ("ix_treatment_outcomes_treatment_id", ["treatment_id"]),
        ("ix_treatment_outcomes_visit_id", ["visit_id"]),
        ("ix_treatment_outcomes_treatment_type", ["treatment_type"]),
        ("ix_treatment_outcomes_protocol_code", ["protocol_code"]),
        ("ix_treatment_outcomes_protocol_version", ["protocol_version"]),
        ("ix_treatment_outcomes_body_region", ["body_region"]),
        ("ix_treatment_outcomes_created_by_user_id", ["created_by_user_id"]),
        ("ix_treatment_outcomes_recorded_at", ["recorded_at"]),
    ):
        op.create_index(
            index_name,
            "treatment_outcomes",
            columns,
            unique=False,
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: treatment outcome data cannot be checked."
        )
    connection = op.get_bind()
    count = connection.scalar(
        sa.text("SELECT count(*) FROM treatment_outcomes")
    )
    if count:
        raise RuntimeError(
            "Downgrade refused: treatment outcome history exists."
        )
    for index_name in (
        "ix_treatment_outcomes_recorded_at",
        "ix_treatment_outcomes_created_by_user_id",
        "ix_treatment_outcomes_body_region",
        "ix_treatment_outcomes_protocol_version",
        "ix_treatment_outcomes_protocol_code",
        "ix_treatment_outcomes_treatment_type",
        "ix_treatment_outcomes_visit_id",
        "ix_treatment_outcomes_treatment_id",
    ):
        op.drop_index(index_name, table_name="treatment_outcomes")
    op.drop_table("treatment_outcomes")
