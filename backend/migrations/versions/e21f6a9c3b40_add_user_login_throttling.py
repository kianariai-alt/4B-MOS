"""Add persistent account-bound login throttling state.

Revision ID: e21f6a9c3b40
Revises: d9a4c7e2f1b6
"""

from alembic import context, op
import sqlalchemy as sa


revision = "e21f6a9c3b40"
down_revision = "d9a4c7e2f1b6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "failed_login_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "failed_login_window_started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "login_locked_until",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_users_failed_login_count_nonnegative",
            "failed_login_count >= 0",
        )


def downgrade():
    # Removing active counters or lockouts silently weakens authentication.
    # Allow only an explicitly verified empty-state downgrade.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: login throttling state cannot be checked."
        )
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM users "
            "WHERE failed_login_count != 0 "
            "OR failed_login_window_started_at IS NOT NULL "
            "OR login_locked_until IS NOT NULL"
        )
    ):
        raise RuntimeError(
            "Downgrade refused: account login throttling state exists."
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(
            "ck_users_failed_login_count_nonnegative",
            type_="check",
        )
        batch_op.drop_column("login_locked_until")
        batch_op.drop_column("failed_login_window_started_at")
        batch_op.drop_column("failed_login_count")
