"""Add immutable clinician-selected evidence briefs.

Revision ID: e6b7c8d9a401
Revises: d51e7a9b2c64
"""

from alembic import context, op
import sqlalchemy as sa


revision = "e6b7c8d9a401"
down_revision = "d51e7a9b2c64"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_evidence_briefs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("intake_id", sa.String(36), nullable=False),
        sa.Column("report_ids", sa.JSON(), nullable=False),
        sa.Column("clinical_context_sha256", sa.String(64), nullable=False),
        sa.Column("knowledge_fact_ids", sa.JSON(), nullable=False),
        sa.Column("knowledge_set_sha256", sa.String(64), nullable=False),
        sa.Column("knowledge_as_of", sa.Date(), nullable=False),
        sa.Column("selection_method", sa.String(30), nullable=False),
        sa.Column("output_type", sa.String(30), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "selection_method = 'clinician_selected'",
            name="ck_clinical_evidence_brief_selection_method",
        ),
        sa.CheckConstraint(
            "output_type = 'evidence_summary'",
            name="ck_clinical_evidence_brief_output_type",
        ),
        sa.CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_clinical_evidence_brief_context_sha256",
        ),
        sa.CheckConstraint(
            "length(knowledge_set_sha256) = 64",
            name="ck_clinical_evidence_brief_knowledge_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_clinical_evidence_brief_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["clinical_intakes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for index_name, columns in (
        ("ix_clinical_evidence_briefs_visit_id", ["visit_id"]),
        ("ix_clinical_evidence_briefs_intake_id", ["intake_id"]),
        ("ix_clinical_evidence_briefs_knowledge_as_of", ["knowledge_as_of"]),
        (
            "ix_clinical_evidence_briefs_created_by_user_id",
            ["created_by_user_id"],
        ),
        ("ix_clinical_evidence_briefs_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "clinical_evidence_briefs",
            columns,
            unique=False,
        )


def downgrade():
    # Evidence briefs are patient-linked clinical provenance. A routine
    # rollback must never erase them or their independently reviewable basis.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: clinical evidence brief data cannot "
            "be checked."
        )
    connection = op.get_bind()
    count = connection.scalar(
        sa.text("SELECT count(*) FROM clinical_evidence_briefs")
    )
    if count:
        raise RuntimeError(
            "Downgrade refused: clinical evidence brief history exists."
        )
    for index_name in (
        "ix_clinical_evidence_briefs_created_at",
        "ix_clinical_evidence_briefs_created_by_user_id",
        "ix_clinical_evidence_briefs_knowledge_as_of",
        "ix_clinical_evidence_briefs_intake_id",
        "ix_clinical_evidence_briefs_visit_id",
    ):
        op.drop_index(index_name, table_name="clinical_evidence_briefs")
    op.drop_table("clinical_evidence_briefs")
