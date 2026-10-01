"""Add physician-owned append-only question banks."""
from alembic import op
import sqlalchemy as sa
revision = "d8a1b4f9e053"
down_revision = "c7f0a3e8d942"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("physician_question_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("physician_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("recorded_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("physician_id", "version", name="uq_question_owner_version"),
        sa.UniqueConstraint("physician_id", "request_key", name="uq_question_owner_request"),
        sa.CheckConstraint("version > 0", name="ck_question_version"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_question_sha"),
        sa.CheckConstraint("action IN ('draft', 'approve', 'retire')", name="ck_question_action"),
        sa.ForeignKeyConstraint(["physician_id"], ["users.id"], name="fk_question_owner", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], name="fk_question_recorder", ondelete="RESTRICT"))
    op.create_index("ix_physician_question_events_physician_id", "physician_question_events", ["physician_id"])

def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM physician_question_events")):
        raise RuntimeError("Downgrade refused: physician question history would be lost.")
    op.drop_table("physician_question_events")
