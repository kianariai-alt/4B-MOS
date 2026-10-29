"""Encrypted, append-only interview-learning source packets."""
from alembic import op
import sqlalchemy as sa

revision = "b9e3a7d1c625"
down_revision = "a1d4e7f0b386"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "visit_learning_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("packet_id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("physician_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recording_id", sa.String(36), nullable=False),
        sa.Column("room_code", sa.String(80), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("client_session_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("recorded_by", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bank_event_id", sa.String(36), sa.ForeignKey("physician_question_events.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("key_id", sa.String(80), nullable=False),
        sa.Column("encrypted_data", sa.LargeBinary(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("packet_id", "version", name="uq_visit_learning_packet_version"),
        sa.UniqueConstraint("physician_id", "request_key", name="uq_visit_learning_owner_request"),
        sa.CheckConstraint("version > 0", name="ck_visit_learning_version"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_visit_learning_sha"),
        sa.CheckConstraint("action IN ('submit', 'bank_draft', 'reject')", name="ck_visit_learning_action"),
    )
    for column in ("packet_id", "visit_id", "physician_id", "room_code"):
        op.create_index("ix_visit_learning_events_" + column, "visit_learning_events", [column])


def downgrade():
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("Offline downgrade cannot verify absence of learning source evidence.")
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM visit_learning_events")):
        raise RuntimeError("Downgrade refused: visit-learning source evidence would be lost.")
    op.drop_table("visit_learning_events")
