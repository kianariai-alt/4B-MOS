"""Add immutable study-to-visit bindings and independent physician reviews.

Revision ID: c24a7b9e0d13
Revises: b12f6c8d4a90
"""

from alembic import op
import sqlalchemy as sa

revision = "c24a7b9e0d13"
down_revision = "b12f6c8d4a90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_study_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("visit_id", sa.String(36), sa.ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("paraclinical_reports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("report_key", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("visit_id", "request_key", name="uq_study_binding_request"),
        sa.UniqueConstraint("visit_id", "report_key", "revision", name="uq_study_binding_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_study_binding_revision"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_study_binding_request_hash"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_study_binding_hash"),
    )
    op.create_index("ix_clinical_study_bindings_visit_id", "clinical_study_bindings", ["visit_id"])
    op.create_table(
        "clinical_study_binding_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.String(36), sa.ForeignKey("clinical_study_bindings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("physician_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("binding_id", "sequence", name="uq_study_binding_review_sequence"),
        sa.UniqueConstraint("binding_id", "request_key", name="uq_study_binding_review_request"),
        sa.CheckConstraint("sequence >= 1", name="ck_study_binding_review_sequence"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_study_binding_review_hash"),
    )
    op.create_index("ix_clinical_study_binding_reviews_binding_id", "clinical_study_binding_reviews", ["binding_id"])


def downgrade():
    # Check all history before any DDL, including on SQLite's non-atomic DDL.
    bind = op.get_bind()
    for name in ("clinical_study_binding_reviews", "clinical_study_bindings"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar():
            raise RuntimeError("Refusing downgrade: study binding evidence would be lost.")
    op.drop_table("clinical_study_binding_reviews")
    op.drop_table("clinical_study_bindings")
