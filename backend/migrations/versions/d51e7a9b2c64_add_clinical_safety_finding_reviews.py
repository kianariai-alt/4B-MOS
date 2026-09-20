"""Add append-only clinical safety finding review events.

Revision ID: d51e7a9b2c64
Revises: c92e4b7a1d30
"""

from alembic import context, op
import sqlalchemy as sa


revision = "d51e7a9b2c64"
down_revision = "c92e4b7a1d30"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_safety_finding_reviews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("finding_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("evaluation_result_sha256", sa.String(64), nullable=False),
        sa.Column("rule_content_sha256", sa.String(64), nullable=False),
        sa.Column("previous_review_sha256", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_clinical_safety_finding_review_sequence",
        ),
        sa.CheckConstraint(
            "action IN ('acknowledged', 'escalated', 'assessed')",
            name="ck_clinical_safety_finding_review_action",
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('requires_action', 'not_applicable', 'action_documented', "
            "'monitoring')",
            name="ck_clinical_safety_finding_review_disposition",
        ),
        sa.CheckConstraint(
            "(action = 'assessed' AND disposition IS NOT NULL) OR "
            "(action != 'assessed' AND disposition IS NULL)",
            name="ck_clinical_safety_finding_review_action_disposition",
        ),
        sa.CheckConstraint(
            "(sequence = 1 AND previous_review_sha256 IS NULL) OR "
            "(sequence > 1 AND previous_review_sha256 IS NOT NULL)",
            name="ck_clinical_safety_finding_review_chain",
        ),
        sa.CheckConstraint(
            "previous_review_sha256 IS NULL OR "
            "length(previous_review_sha256) = 64",
            name="ck_clinical_safety_finding_review_previous_sha256",
        ),
        sa.CheckConstraint(
            "length(evaluation_result_sha256) = 64",
            name="ck_clinical_safety_finding_review_evaluation_sha256",
        ),
        sa.CheckConstraint(
            "length(rule_content_sha256) = 64",
            name="ck_clinical_safety_finding_review_rule_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_clinical_safety_finding_review_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["clinical_safety_findings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_id",
            "sequence",
            name="uq_clinical_safety_finding_review_sequence",
        ),
    )
    for index_name, columns in (
        ("ix_clinical_safety_finding_reviews_finding_id", ["finding_id"]),
        ("ix_clinical_safety_finding_reviews_action", ["action"]),
        ("ix_clinical_safety_finding_reviews_disposition", ["disposition"]),
        (
            "ix_clinical_safety_finding_reviews_created_by_user_id",
            ["created_by_user_id"],
        ),
        ("ix_clinical_safety_finding_reviews_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "clinical_safety_finding_reviews",
            columns,
            unique=False,
        )


def downgrade():
    # Finding reviews are patient-specific clinical governance history. A
    # routine rollback must never erase them or break their hash chain.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: safety finding review data cannot be "
            "checked."
        )
    connection = op.get_bind()
    count = connection.scalar(
        sa.text("SELECT count(*) FROM clinical_safety_finding_reviews")
    )
    if count:
        raise RuntimeError(
            "Downgrade refused: clinical safety finding review history exists."
        )
    for index_name in (
        "ix_clinical_safety_finding_reviews_created_at",
        "ix_clinical_safety_finding_reviews_created_by_user_id",
        "ix_clinical_safety_finding_reviews_disposition",
        "ix_clinical_safety_finding_reviews_action",
        "ix_clinical_safety_finding_reviews_finding_id",
    ):
        op.drop_index(
            index_name,
            table_name="clinical_safety_finding_reviews",
        )
    op.drop_table("clinical_safety_finding_reviews")
