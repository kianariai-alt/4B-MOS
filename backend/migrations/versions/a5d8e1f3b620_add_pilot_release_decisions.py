"""Add immutable human pilot release decisions.

Revision ID: a5d8e1f3b620
Revises: f2c6b8d1a704
"""

from alembic import context, op
import sqlalchemy as sa


revision = "a5d8e1f3b620"
down_revision = "f2c6b8d1a704"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_release_decisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_enrolled_visits", sa.Integer(), nullable=True),
        sa.Column("allowed_protocol_codes", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('authorize', 'hold')",
            name="ck_pilot_release_decision_action",
        ),
        sa.CheckConstraint(
            "length(package_sha256) = 64",
            name="ck_pilot_release_decision_package_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_release_decision_sha256",
        ),
        sa.CheckConstraint(
            "max_enrolled_visits IS NULL OR "
            "max_enrolled_visits BETWEEN 1 AND 100",
            name="ck_pilot_release_decision_max_visits",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["pilot_launch_packages.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            name="uq_pilot_release_decision_package",
        ),
    )
    for index_name, columns in (
        ("ix_pilot_release_decisions_package_id", ["package_id"]),
        ("ix_pilot_release_decisions_action", ["action"]),
        (
            "ix_pilot_release_decisions_decided_by_user_id",
            ["decided_by_user_id"],
        ),
        ("ix_pilot_release_decisions_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "pilot_release_decisions",
            columns,
            unique=False,
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: pilot release decisions cannot "
            "be checked."
        )
    connection = op.get_bind()
    decision_count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_release_decisions")
    )
    if decision_count:
        raise RuntimeError(
            "Downgrade refused: pilot release decision history exists."
        )
    for index_name in (
        "ix_pilot_release_decisions_created_at",
        "ix_pilot_release_decisions_decided_by_user_id",
        "ix_pilot_release_decisions_action",
        "ix_pilot_release_decisions_package_id",
    ):
        op.drop_index(index_name, table_name="pilot_release_decisions")
    op.drop_table("pilot_release_decisions")
