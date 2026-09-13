"""Add completion evidence without backfilling historical sessions.

Revision ID: a71d92cfe604
Revises: c68b24017654
"""
from alembic import context, op
import sqlalchemy as sa

revision = "a71d92cfe604"
down_revision = "c68b24017654"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_finalizations",
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["treatment_sessions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade():
    # Never silently destroy captured clinical evidence. An approved recovery
    # procedure, backups and drained application workers are required instead.
    if context.is_offline_mode():
        raise RuntimeError("Offline downgrade refused: evidence cannot be checked.")
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM session_finalizations")):
        raise RuntimeError("Downgrade refused: finalization evidence exists.")
    op.drop_table("session_finalizations")
