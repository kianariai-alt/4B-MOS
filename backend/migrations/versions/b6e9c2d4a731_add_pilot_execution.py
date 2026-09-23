"""Add bounded controlled-pilot enrollment and stop evidence.

Revision ID: b6e9c2d4a731
Revises: a5d8e1f3b620
"""
from alembic import context, op
import sqlalchemy as sa

revision = "b6e9c2d4a731"
down_revision = "a5d8e1f3b620"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_visit_enrollments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_decision_id", sa.String(36), nullable=False),
        sa.Column("release_decision_sha256", sa.String(64), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("protocol_template_id", sa.String(36), nullable=False),
        sa.Column("protocol_snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("clinician_decision_id", sa.String(36), nullable=False),
        sa.Column("clinician_decision_sha256", sa.String(64), nullable=False),
        sa.Column("consent_evidence_reference", sa.String(500), nullable=False),
        sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clinician_statement", sa.Text(), nullable=False),
        sa.Column("enrolled_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("visit_id", name="uq_pilot_visit_enrollment_visit"),
        sa.CheckConstraint("length(release_decision_sha256) = 64", name="ck_pilot_enrollment_release_sha256"),
        sa.CheckConstraint("length(clinician_decision_sha256) = 64", name="ck_pilot_enrollment_clinician_sha256"),
        sa.CheckConstraint("length(protocol_snapshot_sha256) = 64", name="ck_pilot_enrollment_protocol_sha256"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_pilot_enrollment_sha256"),
        sa.ForeignKeyConstraint(["release_decision_id"], ["pilot_release_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["protocol_template_id"], ["protocol_templates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["clinician_decision_id"], ["treatment_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["enrolled_by_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    for name, columns in (
        ("ix_pilot_visit_enrollments_release_decision_id", ["release_decision_id"]),
        ("ix_pilot_visit_enrollments_visit_id", ["visit_id"]),
        ("ix_pilot_visit_enrollments_created_at", ["created_at"]),
    ):
        op.create_index(name, "pilot_visit_enrollments", columns)
    op.create_table(
        "pilot_stop_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("release_decision_id", sa.String(36), nullable=False),
        sa.Column("release_decision_sha256", sa.String(64), nullable=False),
        sa.Column("reason_category", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("stopped_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_decision_id", name="uq_pilot_stop_decision"),
        sa.CheckConstraint(
            "reason_category IN ('clinical_safety', 'operational', 'privacy', 'other')",
            name="ck_pilot_stop_reason_category",
        ),
        sa.CheckConstraint("length(release_decision_sha256) = 64", name="ck_pilot_stop_release_sha256"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_pilot_stop_sha256"),
        sa.ForeignKeyConstraint(["release_decision_id"], ["pilot_release_decisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stopped_by_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    for name, columns in (
        ("ix_pilot_stop_events_release_decision_id", ["release_decision_id"]),
        ("ix_pilot_stop_events_created_at", ["created_at"]),
    ):
        op.create_index(name, "pilot_stop_events", columns)


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError("Offline downgrade refused: pilot execution history cannot be checked.")
    bind = op.get_bind()
    rows = bind.scalar(sa.text(
        "SELECT (SELECT count(*) FROM pilot_visit_enrollments) + "
        "(SELECT count(*) FROM pilot_stop_events)"
    ))
    if rows:
        raise RuntimeError("Downgrade refused: controlled pilot execution history exists.")
    for name in (
        "ix_pilot_stop_events_created_at",
        "ix_pilot_stop_events_release_decision_id",
    ):
        op.drop_index(name, table_name="pilot_stop_events")
    op.drop_table("pilot_stop_events")
    for name in (
        "ix_pilot_visit_enrollments_created_at",
        "ix_pilot_visit_enrollments_visit_id",
        "ix_pilot_visit_enrollments_release_decision_id",
    ):
        op.drop_index(name, table_name="pilot_visit_enrollments")
    op.drop_table("pilot_visit_enrollments")
