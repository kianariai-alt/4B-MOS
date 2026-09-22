"""Add append-only protocol learning governance.

Revision ID: b7d4e6f8c230
Revises: a3e5c7d9b120
"""

from alembic import context, op
import sqlalchemy as sa


revision = "b7d4e6f8c230"
down_revision = "a3e5c7d9b120"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "protocol_governance_cases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("protocol_code", sa.String(100), nullable=False),
        sa.Column("protocol_version", sa.String(30), nullable=False),
        sa.Column("treatment_type", sa.String(50), nullable=False),
        sa.Column("case_type", sa.String(40), nullable=False),
        sa.Column("source_learning_review_sha256", sa.String(64), nullable=False),
        sa.Column("protocol_snapshot", sa.JSON(), nullable=False),
        sa.Column("learning_snapshot", sa.JSON(), nullable=False),
        sa.Column("proposed_protocol", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_needed", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "case_type IN ("
            "'collect_more_data', 'monitor_no_change', "
            "'revision_candidate', 'deactivation_candidate'"
            ")",
            name="ck_protocol_governance_case_type",
        ),
        sa.CheckConstraint(
            "length(source_learning_review_sha256) = 64",
            name="ck_protocol_governance_learning_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_case_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_protocol_governance_cases_protocol_code",
        "protocol_governance_cases",
        ["protocol_code"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_cases_protocol_version",
        "protocol_governance_cases",
        ["protocol_version"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_cases_case_type",
        "protocol_governance_cases",
        ["case_type"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_cases_created_by_user_id",
        "protocol_governance_cases",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_cases_created_at",
        "protocol_governance_cases",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "protocol_governance_reviews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("case_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("reviewer_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ("
            "'clinical_approve', 'clinical_reject', 'request_changes', "
            "'operational_acknowledge', 'operational_hold'"
            ")",
            name="ck_protocol_governance_review_action",
        ),
        sa.CheckConstraint(
            "length(case_sha256) = 64",
            name="ck_protocol_governance_review_case_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_review_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["protocol_governance_cases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_protocol_governance_reviews_case_id",
        "protocol_governance_reviews",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_reviews_action",
        "protocol_governance_reviews",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_reviews_reviewer_user_id",
        "protocol_governance_reviews",
        ["reviewer_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_protocol_governance_reviews_created_at",
        "protocol_governance_reviews",
        ["created_at"],
        unique=False,
    )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: protocol governance data cannot be checked."
        )
    connection = op.get_bind()
    count = connection.scalar(sa.text(
        "SELECT "
        "(SELECT count(*) FROM protocol_governance_cases) + "
        "(SELECT count(*) FROM protocol_governance_reviews)"
    ))
    if count:
        raise RuntimeError(
            "Downgrade refused: protocol governance history exists."
        )

    for index_name in (
        "ix_protocol_governance_reviews_created_at",
        "ix_protocol_governance_reviews_reviewer_user_id",
        "ix_protocol_governance_reviews_action",
        "ix_protocol_governance_reviews_case_id",
    ):
        op.drop_index(index_name, table_name="protocol_governance_reviews")
    op.drop_table("protocol_governance_reviews")

    for index_name in (
        "ix_protocol_governance_cases_created_at",
        "ix_protocol_governance_cases_created_by_user_id",
        "ix_protocol_governance_cases_case_type",
        "ix_protocol_governance_cases_protocol_version",
        "ix_protocol_governance_cases_protocol_code",
    ):
        op.drop_index(index_name, table_name="protocol_governance_cases")
    op.drop_table("protocol_governance_cases")
