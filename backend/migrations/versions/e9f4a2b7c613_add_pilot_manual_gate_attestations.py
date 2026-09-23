"""Add immutable pilot manual gate attestations and reviews.

Revision ID: e9f4a2b7c613
Revises: d4a7c9e1f562
"""

from alembic import context, op
import sqlalchemy as sa


revision = "e9f4a2b7c613"
down_revision = "d4a7c9e1f562"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_manual_gate_attestations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("gate_name", sa.String(60), nullable=False),
        sa.Column("readiness_sha256", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("release_ref", sa.String(200), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("supersedes_attestation_id", sa.String(36), nullable=True),
        sa.Column("attested_by_user_id", sa.String(36), nullable=False),
        sa.Column("attested_by_role", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "gate_name IN ("
            "'clinical_protocol_signoff', 'clinical_safety_signoff', "
            "'backup_restore', 'security_perimeter', 'monitoring_alerting', "
            "'human_ui_acceptance', 'privacy_retention_legal'"
            ")",
            name="ck_pilot_manual_gate_attestation_name",
        ),
        sa.CheckConstraint(
            "length(readiness_sha256) = 64",
            name="ck_pilot_manual_gate_attestation_readiness_sha256",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_pilot_manual_gate_attestation_generation",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_manual_gate_attestation_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_attestation_id"],
            ["pilot_manual_gate_attestations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attested_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supersedes_attestation_id",
            name="uq_pilot_manual_gate_attestation_supersedes",
        ),
        sa.UniqueConstraint(
            "gate_name",
            "generation",
            name="uq_pilot_manual_gate_attestation_generation",
        ),
    )
    for index_name, columns in (
        (
            "ix_pilot_manual_gate_attestations_gate_name",
            ["gate_name"],
        ),
        (
            "ix_pilot_manual_gate_attestations_supersedes_attestation_id",
            ["supersedes_attestation_id"],
        ),
        (
            "ix_pilot_manual_gate_attestations_attested_by_user_id",
            ["attested_by_user_id"],
        ),
        (
            "ix_pilot_manual_gate_attestations_created_at",
            ["created_at"],
        ),
    ):
        op.create_index(
            index_name,
            "pilot_manual_gate_attestations",
            columns,
            unique=False,
        )

    op.create_table(
        "pilot_manual_gate_reviews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("attestation_id", sa.String(36), nullable=False),
        sa.Column("attestation_sha256", sa.String(64), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(36), nullable=False),
        sa.Column("reviewed_by_role", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('approve', 'reject')",
            name="ck_pilot_manual_gate_review_action",
        ),
        sa.CheckConstraint(
            "length(attestation_sha256) = 64",
            name="ck_pilot_manual_gate_review_attestation_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_manual_gate_review_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["attestation_id"],
            ["pilot_manual_gate_attestations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attestation_id",
            name="uq_pilot_manual_gate_review_attestation",
        ),
    )
    for index_name, columns in (
        (
            "ix_pilot_manual_gate_reviews_attestation_id",
            ["attestation_id"],
        ),
        (
            "ix_pilot_manual_gate_reviews_action",
            ["action"],
        ),
        (
            "ix_pilot_manual_gate_reviews_reviewed_by_user_id",
            ["reviewed_by_user_id"],
        ),
        (
            "ix_pilot_manual_gate_reviews_created_at",
            ["created_at"],
        ),
    ):
        op.create_index(
            index_name,
            "pilot_manual_gate_reviews",
            columns,
            unique=False,
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: pilot attestation history cannot be "
            "checked."
        )
    connection = op.get_bind()
    attestation_count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_manual_gate_attestations")
    )
    review_count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_manual_gate_reviews")
    )
    if attestation_count or review_count:
        raise RuntimeError(
            "Downgrade refused: pilot manual gate history exists."
        )

    for index_name in (
        "ix_pilot_manual_gate_reviews_created_at",
        "ix_pilot_manual_gate_reviews_reviewed_by_user_id",
        "ix_pilot_manual_gate_reviews_action",
        "ix_pilot_manual_gate_reviews_attestation_id",
    ):
        op.drop_index(
            index_name,
            table_name="pilot_manual_gate_reviews",
        )
    op.drop_table("pilot_manual_gate_reviews")

    for index_name in (
        "ix_pilot_manual_gate_attestations_created_at",
        "ix_pilot_manual_gate_attestations_attested_by_user_id",
        "ix_pilot_manual_gate_attestations_supersedes_attestation_id",
        "ix_pilot_manual_gate_attestations_gate_name",
    ):
        op.drop_index(
            index_name,
            table_name="pilot_manual_gate_attestations",
        )
    op.drop_table("pilot_manual_gate_attestations")
