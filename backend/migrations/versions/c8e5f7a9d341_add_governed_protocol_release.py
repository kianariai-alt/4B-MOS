"""Add governed protocol release provenance.

Revision ID: c8e5f7a9d341
Revises: b7d4e6f8c230
"""

from alembic import context, op
import sqlalchemy as sa


revision = "c8e5f7a9d341"
down_revision = "b7d4e6f8c230"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("protocol_templates", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "supersedes_protocol_id",
                sa.String(36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_governance_case_id",
                sa.String(36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_governance_case_sha256",
                sa.String(64),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_protocol_templates_supersedes_protocol_id",
            ["supersedes_protocol_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_protocol_templates_source_governance_case_id",
            ["source_governance_case_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_protocol_templates_supersedes_protocol_id",
            "protocol_templates",
            ["supersedes_protocol_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_protocol_templates_source_governance_case_id",
            "protocol_governance_cases",
            ["source_governance_case_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_protocol_template_governance_sha256",
            "source_governance_case_sha256 IS NULL OR "
            "length(source_governance_case_sha256) = 64",
        )

    op.create_table(
        "protocol_governance_releases",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("case_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("source_protocol_id", sa.String(36), nullable=False),
        sa.Column("released_protocol_id", sa.String(36), nullable=True),
        sa.Column("source_protocol_before", sa.JSON(), nullable=False),
        sa.Column("source_protocol_after", sa.JSON(), nullable=False),
        sa.Column("released_protocol_snapshot", sa.JSON(), nullable=True),
        sa.Column("executed_by_user_id", sa.String(36), nullable=False),
        sa.Column("execution_note", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('publish_revision', 'deactivate')",
            name="ck_protocol_governance_release_action",
        ),
        sa.CheckConstraint(
            "length(case_sha256) = 64",
            name="ck_protocol_governance_release_case_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_release_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["protocol_governance_cases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_protocol_id"],
            ["protocol_templates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["released_protocol_id"],
            ["protocol_templates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["executed_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            name="uq_protocol_governance_release_case",
        ),
    )
    for index_name, columns in (
        ("ix_protocol_governance_releases_case_id", ["case_id"]),
        ("ix_protocol_governance_releases_action", ["action"]),
        (
            "ix_protocol_governance_releases_source_protocol_id",
            ["source_protocol_id"],
        ),
        (
            "ix_protocol_governance_releases_released_protocol_id",
            ["released_protocol_id"],
        ),
        (
            "ix_protocol_governance_releases_executed_by_user_id",
            ["executed_by_user_id"],
        ),
        ("ix_protocol_governance_releases_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "protocol_governance_releases",
            columns,
            unique=False,
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: governed release data cannot be checked."
        )
    connection = op.get_bind()
    release_count = connection.scalar(
        sa.text("SELECT count(*) FROM protocol_governance_releases")
    )
    lineage_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM protocol_templates "
            "WHERE supersedes_protocol_id IS NOT NULL "
            "OR source_governance_case_id IS NOT NULL "
            "OR source_governance_case_sha256 IS NOT NULL"
        )
    )
    if release_count or lineage_count:
        raise RuntimeError(
            "Downgrade refused: governed protocol release history exists."
        )

    for index_name in (
        "ix_protocol_governance_releases_created_at",
        "ix_protocol_governance_releases_executed_by_user_id",
        "ix_protocol_governance_releases_released_protocol_id",
        "ix_protocol_governance_releases_source_protocol_id",
        "ix_protocol_governance_releases_action",
        "ix_protocol_governance_releases_case_id",
    ):
        op.drop_index(
            index_name,
            table_name="protocol_governance_releases",
        )
    op.drop_table("protocol_governance_releases")

    with op.batch_alter_table("protocol_templates", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_protocol_template_governance_sha256",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_protocol_templates_source_governance_case_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_protocol_templates_supersedes_protocol_id",
            type_="foreignkey",
        )
        batch_op.drop_index(
            "ix_protocol_templates_source_governance_case_id"
        )
        batch_op.drop_index(
            "ix_protocol_templates_supersedes_protocol_id"
        )
        batch_op.drop_column("source_governance_case_sha256")
        batch_op.drop_column("source_governance_case_id")
        batch_op.drop_column("supersedes_protocol_id")
