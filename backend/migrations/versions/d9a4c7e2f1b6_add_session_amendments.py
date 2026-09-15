"""Add append-only session amendments and final review decisions.

Revision ID: d9a4c7e2f1b6
Revises: b36e7f0a1d42
"""

from alembic import context, op
import sqlalchemy as sa


revision = "d9a4c7e2f1b6"
down_revision = "b36e7f0a1d42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "session_amendments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_session_amendments_sequence_positive",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["session_finalizations.session_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_session_amendments_session_sequence",
        ),
    )
    op.create_index(
        "ix_session_amendments_session_id",
        "session_amendments",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "session_amendment_reviews",
        sa.Column("amendment_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_session_amendment_reviews_decision",
        ),
        sa.ForeignKeyConstraint(
            ["amendment_id"],
            ["session_amendments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("amendment_id"),
    )


def downgrade():
    # Approved, rejected and still-pending amendments are all clinical history.
    # Never silently destroy them through a routine downgrade.
    if context.is_offline_mode():
        raise RuntimeError("Offline downgrade refused: amendments cannot be checked.")
    connection = op.get_bind()
    amendments = connection.scalar(sa.text("SELECT count(*) FROM session_amendments"))
    reviews = connection.scalar(sa.text("SELECT count(*) FROM session_amendment_reviews"))
    if amendments or reviews:
        raise RuntimeError("Downgrade refused: session amendment history exists.")
    op.drop_table("session_amendment_reviews")
    op.drop_index(
        "ix_session_amendments_session_id",
        table_name="session_amendments",
    )
    op.drop_table("session_amendments")
