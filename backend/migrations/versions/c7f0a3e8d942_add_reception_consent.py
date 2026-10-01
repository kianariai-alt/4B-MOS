"""Add append-only administrative reception and visit-specific consent.
Revision ID: c7f0a3e8d942
Revises: b6e9c2d4a731
"""

from alembic import op
import sqlalchemy as sa

revision = "c7f0a3e8d942"
down_revision = "b6e9c2d4a731"
branch_labels = None
depends_on = None


def upgrade():
    for name, prefix in (
        ("reception_revisions", "reception"),
        ("visit_consent_events", "consent"),
    ):
        op.create_table(
            name,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("visit_id", sa.String(36), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("request_key", sa.String(100), nullable=False),
            sa.Column("recorded_by", sa.String(36), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "visit_id", "version", name=f"uq_{prefix}_visit_version"
            ),
            sa.UniqueConstraint(
                "visit_id", "request_key", name=f"uq_{prefix}_visit_request"
            ),
            sa.CheckConstraint("version > 0", name=f"ck_{prefix}_version"),
            sa.CheckConstraint("length(sha256) = 64", name=f"ck_{prefix}_sha"),
            sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="RESTRICT"),
        )
        op.create_index(f"ix_{name}_visit_id", name, ["visit_id"])


def downgrade():
    bind = op.get_bind()
    if any(
        bind.scalar(sa.text(f"SELECT COUNT(*) FROM {name}"))
        for name in ("reception_revisions", "visit_consent_events")
    ):
        raise RuntimeError(
            "Downgrade refused: reception/consent evidence would be lost."
        )
    op.drop_table("visit_consent_events")
    op.drop_table("reception_revisions")
