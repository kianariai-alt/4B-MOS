"""Add governed protocol recovery and lineage provenance.

Revision ID: d4a7c9e1f562
Revises: c8e5f7a9d341
"""

from alembic import context, op
import sqlalchemy as sa


revision = "d4a7c9e1f562"
down_revision = "c8e5f7a9d341"
branch_labels = None
depends_on = None


RECOVERY_CASE_TYPES = (
    "reactivation_candidate",
    "rollback_revision_candidate",
)


def _set_sqlite_foreign_keys(enabled: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}"
        )


def upgrade():
    _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table(
            "protocol_governance_cases",
            schema=None,
        ) as batch_op:
            batch_op.drop_constraint(
                "ck_protocol_governance_case_type",
                type_="check",
            )
            batch_op.add_column(
                sa.Column(
                    "source_release_id",
                    sa.String(36),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "source_release_sha256",
                    sa.String(64),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "recovery_snapshot",
                    sa.JSON(none_as_null=True),
                    nullable=True,
                )
            )
            batch_op.create_index(
                "ix_protocol_governance_cases_source_release_id",
                ["source_release_id"],
                unique=False,
            )
            batch_op.create_check_constraint(
                "ck_protocol_governance_case_type",
                "case_type IN ("
                "'collect_more_data', 'monitor_no_change', "
                "'revision_candidate', 'deactivation_candidate', "
                "'reactivation_candidate', 'rollback_revision_candidate'"
                ")",
            )
            batch_op.create_check_constraint(
                "ck_protocol_governance_source_release_sha256",
                "source_release_sha256 IS NULL OR "
                "length(source_release_sha256) = 64",
            )
            batch_op.create_check_constraint(
                "ck_protocol_governance_recovery_case_fields",
                "("
                "case_type IN "
                "('reactivation_candidate', 'rollback_revision_candidate') "
                "AND source_release_id IS NOT NULL "
                "AND source_release_sha256 IS NOT NULL "
                "AND recovery_snapshot IS NOT NULL"
                ") OR ("
                "case_type NOT IN "
                "('reactivation_candidate', 'rollback_revision_candidate') "
                "AND source_release_id IS NULL "
                "AND source_release_sha256 IS NULL "
                "AND recovery_snapshot IS NULL"
                ")",
            )
    finally:
        _set_sqlite_foreign_keys(True)

    op.create_table(
        "protocol_governance_recoveries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("case_sha256", sa.String(64), nullable=False),
        sa.Column("source_release_id", sa.String(36), nullable=False),
        sa.Column("source_release_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("deactivated_protocol_id", sa.String(36), nullable=True),
        sa.Column("reactivated_protocol_id", sa.String(36), nullable=False),
        sa.Column("before_snapshots", sa.JSON(), nullable=False),
        sa.Column("after_snapshots", sa.JSON(), nullable=False),
        sa.Column("executed_by_user_id", sa.String(36), nullable=False),
        sa.Column("execution_note", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('reactivate', 'rollback_revision')",
            name="ck_protocol_governance_recovery_action",
        ),
        sa.CheckConstraint(
            "length(case_sha256) = 64",
            name="ck_protocol_governance_recovery_case_sha256",
        ),
        sa.CheckConstraint(
            "length(source_release_sha256) = 64",
            name="ck_protocol_governance_recovery_release_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_protocol_governance_recovery_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["protocol_governance_cases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_release_id"],
            ["protocol_governance_releases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deactivated_protocol_id"],
            ["protocol_templates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reactivated_protocol_id"],
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
            name="uq_protocol_governance_recovery_case",
        ),
        sa.UniqueConstraint(
            "source_release_id",
            name="uq_protocol_governance_recovery_source_release",
        ),
    )
    for index_name, columns in (
        ("ix_protocol_governance_recoveries_case_id", ["case_id"]),
        (
            "ix_protocol_governance_recoveries_source_release_id",
            ["source_release_id"],
        ),
        ("ix_protocol_governance_recoveries_action", ["action"]),
        (
            "ix_protocol_governance_recoveries_deactivated_protocol_id",
            ["deactivated_protocol_id"],
        ),
        (
            "ix_protocol_governance_recoveries_reactivated_protocol_id",
            ["reactivated_protocol_id"],
        ),
        (
            "ix_protocol_governance_recoveries_executed_by_user_id",
            ["executed_by_user_id"],
        ),
        (
            "ix_protocol_governance_recoveries_created_at",
            ["created_at"],
        ),
    ):
        op.create_index(
            index_name,
            "protocol_governance_recoveries",
            columns,
            unique=False,
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: governed recovery history cannot "
            "be checked."
        )

    connection = op.get_bind()
    recovery_count = connection.scalar(
        sa.text("SELECT count(*) FROM protocol_governance_recoveries")
    )
    recovery_case_count = connection.scalar(
        sa.text(
            "SELECT count(*) FROM protocol_governance_cases "
            "WHERE case_type IN "
            "('reactivation_candidate', 'rollback_revision_candidate') "
            "OR source_release_id IS NOT NULL "
            "OR source_release_sha256 IS NOT NULL "
            "OR recovery_snapshot IS NOT NULL"
        )
    )
    if recovery_count or recovery_case_count:
        raise RuntimeError(
            "Downgrade refused: governed protocol recovery history exists."
        )

    for index_name in (
        "ix_protocol_governance_recoveries_created_at",
        "ix_protocol_governance_recoveries_executed_by_user_id",
        "ix_protocol_governance_recoveries_reactivated_protocol_id",
        "ix_protocol_governance_recoveries_deactivated_protocol_id",
        "ix_protocol_governance_recoveries_action",
        "ix_protocol_governance_recoveries_source_release_id",
        "ix_protocol_governance_recoveries_case_id",
    ):
        op.drop_index(
            index_name,
            table_name="protocol_governance_recoveries",
        )
    op.drop_table("protocol_governance_recoveries")

    _set_sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table(
            "protocol_governance_cases",
            schema=None,
        ) as batch_op:
            batch_op.drop_constraint(
                "ck_protocol_governance_recovery_case_fields",
                type_="check",
            )
            batch_op.drop_constraint(
                "ck_protocol_governance_source_release_sha256",
                type_="check",
            )
            batch_op.drop_constraint(
                "ck_protocol_governance_case_type",
                type_="check",
            )
            batch_op.drop_index(
                "ix_protocol_governance_cases_source_release_id"
            )
            batch_op.drop_column("recovery_snapshot")
            batch_op.drop_column("source_release_sha256")
            batch_op.drop_column("source_release_id")
            batch_op.create_check_constraint(
                "ck_protocol_governance_case_type",
                "case_type IN ("
                "'collect_more_data', 'monitor_no_change', "
                "'revision_candidate', 'deactivation_candidate'"
                ")",
            )
    finally:
        _set_sqlite_foreign_keys(True)
