"""Add per-account token revocation version.

Revision ID: b36e7f0a1d42
Revises: a71d92cfe604
"""
from alembic import context, op
import sqlalchemy as sa


revision = "b36e7f0a1d42"
down_revision = "a71d92cfe604"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "auth_version",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_users_auth_version_nonnegative",
            "auth_version >= 0",
        )


def downgrade():
    # Removing a non-zero version would make revoked sessions valid again when
    # paired with older application code, so refuse any lossy downgrade.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: account revocation state cannot be checked."
        )
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM users WHERE auth_version != 0")
    ):
        raise RuntimeError(
            "Downgrade refused: revoked account sessions exist."
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint(
            "ck_users_auth_version_nonnegative",
            type_="check",
        )
        batch_op.drop_column("auth_version")
