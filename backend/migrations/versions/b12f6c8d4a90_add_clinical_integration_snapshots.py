"""Add experimental immutable clinical integration snapshots and reviews.

Revision ID: b12f6c8d4a90
Revises: a1d4e7f0b386
"""

from alembic import op
import sqlalchemy as sa

revision = "b12f6c8d4a90"
down_revision = "a1d4e7f0b386"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_integration_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("visit_id", sa.String(36), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("visit_id", "request_key", name="uq_integration_run_request"),
        sa.CheckConstraint("length(result_sha256) = 64", name="ck_integration_result_hash"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_integration_request_hash"),
    )
    op.create_index("ix_clinical_integration_runs_visit_id", "clinical_integration_runs", ["visit_id"])
    op.create_index("ix_clinical_integration_runs_created_at", "clinical_integration_runs", ["created_at"])
    op.create_table(
        "clinical_integration_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("clinical_integration_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("physician_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "request_key", name="uq_integration_review_request"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_integration_review_hash"),
    )
    op.create_index("ix_clinical_integration_reviews_run_id", "clinical_integration_reviews", ["run_id"])


def downgrade():
    bind = op.get_bind()
    for name in ("clinical_integration_reviews", "clinical_integration_runs"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar():
            raise RuntimeError("Refusing downgrade: integration evidence would be lost.")
    op.drop_table("clinical_integration_reviews")
    op.drop_table("clinical_integration_runs")
