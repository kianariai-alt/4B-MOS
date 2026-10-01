"""Add append-only capture authorization and local completion metadata."""
from alembic import op
import sqlalchemy as sa
revision="e9b2c5a0f164"
down_revision="d8a1b4f9e053"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("visit_recording_events",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("visit_id",sa.String(36),nullable=False),
        sa.Column("recording_id",sa.String(36),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("action",sa.String(20),nullable=False),
        sa.Column("request_key",sa.String(100),nullable=False),
        sa.Column("recorded_by",sa.String(36),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("payload",sa.JSON(),nullable=False),
        sa.Column("sha256",sa.String(64),nullable=False),
        sa.UniqueConstraint("visit_id","version",name="uq_recording_visit_version"),
        sa.UniqueConstraint("recording_id","action",name="uq_recording_id_action"),
        sa.UniqueConstraint("visit_id","request_key",name="uq_recording_visit_request"),
        sa.CheckConstraint("version > 0",name="ck_recording_version"),
        sa.CheckConstraint("length(sha256) = 64",name="ck_recording_sha"),
        sa.CheckConstraint("action IN ('start', 'finish')",name="ck_recording_action"),
        sa.ForeignKeyConstraint(["visit_id"],["visits.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by"],["users.id"],ondelete="RESTRICT"))
    op.create_index("ix_visit_recording_events_visit_id","visit_recording_events",["visit_id"])
    op.create_index("ix_visit_recording_events_recording_id","visit_recording_events",["recording_id"])

def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM visit_recording_events")):
        raise RuntimeError("Downgrade refused: recording evidence would be lost.")
    op.drop_table("visit_recording_events")
