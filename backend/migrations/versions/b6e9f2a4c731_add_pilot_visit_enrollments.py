"""Add versioned controlled-pilot visit enrollments.

Revision ID: b6e9f2a4c731
Revises: a5d8e1f3b620
"""

from alembic import context, op
import sqlalchemy as sa


revision = "b6e9f2a4c731"
down_revision = "a5d8e1f3b620"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_visit_enrollments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("supersedes_enrollment_id", sa.String(36), nullable=True),
        sa.Column("release_decision_id", sa.String(36), nullable=False),
        sa.Column("release_decision_sha256", sa.String(64), nullable=False),
        sa.Column("clinical_context_sha256", sa.String(64), nullable=False),
        sa.Column("protocol_template_id", sa.String(36), nullable=False),
        sa.Column("protocol_code", sa.String(100), nullable=False),
        sa.Column("protocol_version", sa.String(30), nullable=False),
        sa.Column("treatment_type", sa.String(50), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("enrolled_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_pilot_visit_enrollment_generation",
        ),
        sa.CheckConstraint(
            "length(release_decision_sha256) = 64",
            name="ck_pilot_visit_enrollment_release_sha256",
        ),
        sa.CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_pilot_visit_enrollment_context_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_visit_enrollment_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_enrollment_id"],
            ["pilot_visit_enrollments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_decision_id"],
            ["pilot_release_decisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["protocol_template_id"],
            ["protocol_templates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["enrolled_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "visit_id",
            "generation",
            name="uq_pilot_visit_enrollment_generation",
        ),
        sa.UniqueConstraint(
            "supersedes_enrollment_id",
            name="uq_pilot_visit_enrollment_supersedes",
        ),
    )
    for index_name, columns in (
        ("ix_pilot_visit_enrollments_visit_id", ["visit_id"]),
        (
            "ix_pilot_visit_enrollments_supersedes_enrollment_id",
            ["supersedes_enrollment_id"],
        ),
        (
            "ix_pilot_visit_enrollments_release_decision_id",
            ["release_decision_id"],
        ),
        (
            "ix_pilot_visit_enrollments_protocol_template_id",
            ["protocol_template_id"],
        ),
        (
            "ix_pilot_visit_enrollments_enrolled_by_user_id",
            ["enrolled_by_user_id"],
        ),
        ("ix_pilot_visit_enrollments_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "pilot_visit_enrollments",
            columns,
            unique=False,
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: pilot visit enrollments cannot be checked."
        )
    connection = op.get_bind()
    count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_visit_enrollments")
    )
    if count:
        raise RuntimeError(
            "Downgrade refused: pilot visit enrollment history exists."
        )
    for index_name in (
        "ix_pilot_visit_enrollments_created_at",
        "ix_pilot_visit_enrollments_enrolled_by_user_id",
        "ix_pilot_visit_enrollments_protocol_template_id",
        "ix_pilot_visit_enrollments_release_decision_id",
        "ix_pilot_visit_enrollments_supersedes_enrollment_id",
        "ix_pilot_visit_enrollments_visit_id",
    ):
        op.drop_index(index_name, table_name="pilot_visit_enrollments")
    op.drop_table("pilot_visit_enrollments")
