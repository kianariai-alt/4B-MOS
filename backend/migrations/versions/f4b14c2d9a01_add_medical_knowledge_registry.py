"""Add versioned, review-gated medical knowledge registry.

Revision ID: f4b14c2d9a01
Revises: e21f6a9c3b40
"""

from alembic import context, op
import sqlalchemy as sa


revision = "f4b14c2d9a01"
down_revision = "e21f6a9c3b40"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "medical_knowledge_facts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("fact_key", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("clinical_domain", sa.String(100), nullable=False),
        sa.Column("therapy_type", sa.String(50), nullable=True),
        sa.Column("population", sa.Text(), nullable=True),
        sa.Column("indication", sa.Text(), nullable=True),
        sa.Column(
            "contraindications",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("evidence_grade", sa.String(30), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("supersedes_fact_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_medical_knowledge_facts_version_positive",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_medical_knowledge_facts_row_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'retired')",
            name="ck_medical_knowledge_facts_status",
        ),
        sa.CheckConstraint(
            "evidence_grade IN "
            "('high', 'moderate', 'low', 'very_low', 'consensus', 'ungraded')",
            name="ck_medical_knowledge_facts_evidence_grade",
        ),
        sa.CheckConstraint(
            "therapy_type IS NULL OR therapy_type IN "
            "('PRP', 'PRGF', 'ACS', 'PL', 'SVF', 'EXOSOME', 'MSC')",
            name="ck_medical_knowledge_facts_therapy_type",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_medical_knowledge_facts_valid_dates",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_fact_id"],
            ["medical_knowledge_facts.id"],
            ondelete="NO ACTION",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fact_key",
            "version",
            name="uq_medical_knowledge_facts_key_version",
        ),
        sa.UniqueConstraint(
            "supersedes_fact_id",
            name="uq_medical_knowledge_facts_supersedes",
        ),
    )
    op.create_index(
        "ix_medical_knowledge_facts_fact_key",
        "medical_knowledge_facts",
        ["fact_key"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_status",
        "medical_knowledge_facts",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_clinical_domain",
        "medical_knowledge_facts",
        ["clinical_domain"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_therapy_type",
        "medical_knowledge_facts",
        ["therapy_type"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_evidence_grade",
        "medical_knowledge_facts",
        ["evidence_grade"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_supersedes_fact_id",
        "medical_knowledge_facts",
        ["supersedes_fact_id"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_created_by_user_id",
        "medical_knowledge_facts",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_medical_knowledge_facts_reviewed_by_user_id",
        "medical_knowledge_facts",
        ["reviewed_by_user_id"],
        unique=False,
    )

    op.create_table(
        "medical_knowledge_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("fact_id", sa.String(36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("citation", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=True),
        sa.Column("url", sa.String(2000), nullable=True),
        sa.Column("doi", sa.String(255), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("guideline_version", sa.String(100), nullable=True),
        sa.Column("accessed_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_medical_knowledge_sources_order_positive",
        ),
        sa.CheckConstraint(
            "source_type IN "
            "('guideline', 'systematic_review', 'randomized_trial', "
            "'observational_study', 'regulatory', 'consensus', "
            "'textbook', 'other')",
            name="ck_medical_knowledge_sources_type",
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"],
            ["medical_knowledge_facts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fact_id",
            "sort_order",
            name="uq_medical_knowledge_sources_fact_order",
        ),
    )
    op.create_index(
        "ix_medical_knowledge_sources_fact_id",
        "medical_knowledge_sources",
        ["fact_id"],
        unique=False,
    )


def downgrade():
    # Knowledge content and its review history are controlled clinical assets.
    # Routine downgrade must never silently erase even draft or retired facts.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: medical knowledge cannot be checked."
        )
    connection = op.get_bind()
    fact_count = connection.scalar(
        sa.text("SELECT count(*) FROM medical_knowledge_facts")
    )
    source_count = connection.scalar(
        sa.text("SELECT count(*) FROM medical_knowledge_sources")
    )
    if fact_count or source_count:
        raise RuntimeError(
            "Downgrade refused: medical knowledge registry contains data."
        )
    op.drop_index(
        "ix_medical_knowledge_sources_fact_id",
        table_name="medical_knowledge_sources",
    )
    op.drop_table("medical_knowledge_sources")
    op.drop_index(
        "ix_medical_knowledge_facts_reviewed_by_user_id",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_created_by_user_id",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_supersedes_fact_id",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_evidence_grade",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_therapy_type",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_clinical_domain",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_status",
        table_name="medical_knowledge_facts",
    )
    op.drop_index(
        "ix_medical_knowledge_facts_fact_key",
        table_name="medical_knowledge_facts",
    )
    op.drop_table("medical_knowledge_facts")
