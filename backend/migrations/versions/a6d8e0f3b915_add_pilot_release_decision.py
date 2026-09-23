"""Add physician endorsement and admin pilot release decision.

Revision ID: a6d8e0f3b915
Revises: f2c6b8d1a704
"""

from alembic import context, op
import sqlalchemy as sa


revision = "a6d8e0f3b915"
down_revision = "f2c6b8d1a704"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_release_endorsements",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("endorsed_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('endorse', 'hold')",
            name="ck_pilot_release_endorsement_action",
        ),
        sa.CheckConstraint(
            "length(package_sha256) = 64",
            name="ck_pilot_release_endorsement_package_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_release_endorsement_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["pilot_launch_packages.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["endorsed_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            name="uq_pilot_release_endorsement_package",
        ),
    )
    for index_name, columns in (
        ("ix_pilot_release_endorsements_package_id", ["package_id"]),
        ("ix_pilot_release_endorsements_action", ["action"]),
        (
            "ix_pilot_release_endorsements_endorsed_by_user_id",
            ["endorsed_by_user_id"],
        ),
        ("ix_pilot_release_endorsements_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "pilot_release_endorsements",
            columns,
            unique=False,
        )

    op.create_table(
        "pilot_release_decisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("endorsement_id", sa.String(36), nullable=False),
        sa.Column("endorsement_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('authorize_controlled_pilot', 'hold')",
            name="ck_pilot_release_decision_action",
        ),
        sa.CheckConstraint(
            "length(package_sha256) = 64",
            name="ck_pilot_release_decision_package_sha256",
        ),
        sa.CheckConstraint(
            "length(endorsement_sha256) = 64",
            name="ck_pilot_release_decision_endorsement_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_release_decision_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["pilot_launch_packages.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["endorsement_id"],
            ["pilot_release_endorsements.id"],
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
        ("ix_pilot_release_decisions_endorsement_id", ["endorsement_id"]),
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
            "Offline downgrade refused: pilot release decisions cannot be checked."
        )
    connection = op.get_bind()
    decision_count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_release_decisions")
    )
    endorsement_count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_release_endorsements")
    )
    if decision_count or endorsement_count:
        raise RuntimeError(
            "Downgrade refused: pilot release decision history exists."
        )

    for index_name in (
        "ix_pilot_release_decisions_created_at",
        "ix_pilot_release_decisions_decided_by_user_id",
        "ix_pilot_release_decisions_action",
        "ix_pilot_release_decisions_endorsement_id",
        "ix_pilot_release_decisions_package_id",
    ):
        op.drop_index(index_name, table_name="pilot_release_decisions")
    op.drop_table("pilot_release_decisions")

    for index_name in (
        "ix_pilot_release_endorsements_created_at",
        "ix_pilot_release_endorsements_endorsed_by_user_id",
        "ix_pilot_release_endorsements_action",
        "ix_pilot_release_endorsements_package_id",
    ):
        op.drop_index(index_name, table_name="pilot_release_endorsements")
    op.drop_table("pilot_release_endorsements")
