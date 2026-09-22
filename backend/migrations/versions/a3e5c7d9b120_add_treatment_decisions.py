"""Add immutable clinician treatment decisions and treatment provenance.

Revision ID: a3e5c7d9b120
Revises: f7c2d4e8a910
"""

from alembic import context, op
import sqlalchemy as sa


revision = "a3e5c7d9b120"
down_revision = "f7c2d4e8a910"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "treatment_decisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("supersedes_decision_id", sa.String(36), nullable=True),
        sa.Column("decision_type", sa.String(40), nullable=False),
        sa.Column("clinical_context_sha256", sa.String(64), nullable=False),
        sa.Column("roadmap_sha256", sa.String(64), nullable=False),
        sa.Column("selected_protocols", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("modification_summary", sa.Text(), nullable=True),
        sa.Column("patient_preference_summary", sa.Text(), nullable=True),
        sa.Column("evidence_brief_ids", sa.JSON(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision_type IN ("
            "'select_option', 'modify_option', 'combine_options', "
            "'choose_outside_roadmap', 'defer', 'no_treatment'"
            ")",
            name="ck_treatment_decision_type",
        ),
        sa.CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_treatment_decision_context_sha256",
        ),
        sa.CheckConstraint(
            "length(roadmap_sha256) = 64",
            name="ck_treatment_decision_roadmap_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_treatment_decision_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for index_name, columns in (
        ("ix_treatment_decisions_visit_id", ["visit_id"]),
        (
            "ix_treatment_decisions_supersedes_decision_id",
            ["supersedes_decision_id"],
        ),
        ("ix_treatment_decisions_decision_type", ["decision_type"]),
        (
            "ix_treatment_decisions_decided_by_user_id",
            ["decided_by_user_id"],
        ),
        ("ix_treatment_decisions_decided_at", ["decided_at"]),
    ):
        op.create_index(
            index_name,
            "treatment_decisions",
            columns,
            unique=False,
        )

    with op.batch_alter_table("treatments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_treatment_decision_id",
                sa.String(36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_treatment_decision_sha256",
                sa.String(64),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_treatments_source_treatment_decision_id",
            ["source_treatment_decision_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_treatments_source_treatment_decision_id",
            "treatment_decisions",
            ["source_treatment_decision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_treatments_source_decision_sha256",
            "source_treatment_decision_sha256 IS NULL OR "
            "length(source_treatment_decision_sha256) = 64",
        )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: clinician decision data cannot be checked."
        )
    connection = op.get_bind()
    linked = connection.scalar(
        sa.text(
            "SELECT count(*) FROM treatments "
            "WHERE source_treatment_decision_id IS NOT NULL"
        )
    )
    decisions = connection.scalar(
        sa.text("SELECT count(*) FROM treatment_decisions")
    )
    if linked or decisions:
        raise RuntimeError(
            "Downgrade refused: clinician treatment decision history exists."
        )

    with op.batch_alter_table("treatments", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_treatments_source_decision_sha256",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_treatments_source_treatment_decision_id",
            type_="foreignkey",
        )
        batch_op.drop_index(
            "ix_treatments_source_treatment_decision_id"
        )
        batch_op.drop_column("source_treatment_decision_sha256")
        batch_op.drop_column("source_treatment_decision_id")

    for index_name in (
        "ix_treatment_decisions_decided_at",
        "ix_treatment_decisions_decided_by_user_id",
        "ix_treatment_decisions_decision_type",
        "ix_treatment_decisions_supersedes_decision_id",
        "ix_treatment_decisions_visit_id",
    ):
        op.drop_index(index_name, table_name="treatment_decisions")
    op.drop_table("treatment_decisions")
