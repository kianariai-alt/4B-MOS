"""Add governed deterministic clinical safety rule engine.

Revision ID: c92e4b7a1d30
Revises: a8c15d3e7b02
"""

from alembic import context, op
import sqlalchemy as sa


revision = "c92e4b7a1d30"
down_revision = "a8c15d3e7b02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clinical_safety_rules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("rule_key", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("clinical_domain", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("predicate", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("supersedes_rule_id", sa.String(36), nullable=True),
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
            name="ck_clinical_safety_rule_version",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_clinical_safety_rule_row_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'retired')",
            name="ck_clinical_safety_rule_status",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'high', 'critical')",
            name="ck_clinical_safety_rule_severity",
        ),
        sa.CheckConstraint(
            "action IN ('document', 'review_before_proceeding', "
            "'urgent_clinical_review')",
            name="ck_clinical_safety_rule_action",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_clinical_safety_rule_sha256",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_clinical_safety_rule_valid_dates",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_rule_id"],
            ["clinical_safety_rules.id"],
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
            "rule_key",
            "version",
            name="uq_clinical_safety_rule_key_version",
        ),
        sa.UniqueConstraint(
            "supersedes_rule_id",
            name="uq_clinical_safety_rule_supersedes",
        ),
    )
    for index_name, columns in (
        ("ix_clinical_safety_rules_rule_key", ["rule_key"]),
        ("ix_clinical_safety_rules_clinical_domain", ["clinical_domain"]),
        ("ix_clinical_safety_rules_severity", ["severity"]),
        ("ix_clinical_safety_rules_status", ["status"]),
        ("ix_clinical_safety_rules_supersedes_rule_id", ["supersedes_rule_id"]),
        ("ix_clinical_safety_rules_created_by_user_id", ["created_by_user_id"]),
        ("ix_clinical_safety_rules_reviewed_by_user_id", ["reviewed_by_user_id"]),
    ):
        op.create_index(
            index_name,
            "clinical_safety_rules",
            columns,
            unique=False,
        )

    op.create_table(
        "clinical_safety_rule_knowledge",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("rule_id", sa.String(36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("medical_knowledge_fact_id", sa.String(36), nullable=False),
        sa.Column("fact_content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_clinical_safety_rule_knowledge_order",
        ),
        sa.CheckConstraint(
            "length(fact_content_sha256) = 64",
            name="ck_clinical_safety_rule_knowledge_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["clinical_safety_rules.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["medical_knowledge_fact_id"],
            ["medical_knowledge_facts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id",
            "sort_order",
            name="uq_clinical_safety_rule_knowledge_order",
        ),
        sa.UniqueConstraint(
            "rule_id",
            "medical_knowledge_fact_id",
            name="uq_clinical_safety_rule_knowledge_fact",
        ),
    )
    op.create_index(
        "ix_clinical_safety_rule_knowledge_rule_id",
        "clinical_safety_rule_knowledge",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        "ix_clinical_safety_rule_knowledge_medical_knowledge_fact_id",
        "clinical_safety_rule_knowledge",
        ["medical_knowledge_fact_id"],
        unique=False,
    )

    op.create_table(
        "clinical_safety_evaluations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("visit_id", sa.String(36), nullable=False),
        sa.Column("intake_id", sa.String(36), nullable=True),
        sa.Column(
            "report_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("engine_version", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("evaluated_rule_count", sa.Integer(), nullable=False),
        sa.Column("triggered_count", sa.Integer(), nullable=False),
        sa.Column("highest_severity", sa.String(20), nullable=True),
        sa.Column("clinical_context_sha256", sa.String(64), nullable=False),
        sa.Column("rule_set_sha256", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("evaluated_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('alerts_present', 'no_alerts', 'no_active_rules')",
            name="ck_clinical_safety_evaluation_outcome",
        ),
        sa.CheckConstraint(
            "evaluated_rule_count >= 0 AND triggered_count >= 0 "
            "AND triggered_count <= evaluated_rule_count",
            name="ck_clinical_safety_evaluation_counts",
        ),
        sa.CheckConstraint(
            "highest_severity IS NULL OR highest_severity IN "
            "('info', 'warning', 'high', 'critical')",
            name="ck_clinical_safety_evaluation_severity",
        ),
        sa.CheckConstraint(
            "length(clinical_context_sha256) = 64",
            name="ck_clinical_safety_evaluation_context_sha256",
        ),
        sa.CheckConstraint(
            "length(rule_set_sha256) = 64",
            name="ck_clinical_safety_evaluation_rule_set_sha256",
        ),
        sa.CheckConstraint(
            "length(result_sha256) = 64",
            name="ck_clinical_safety_evaluation_result_sha256",
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
            ["evaluated_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for index_name, columns in (
        ("ix_clinical_safety_evaluations_visit_id", ["visit_id"]),
        ("ix_clinical_safety_evaluations_intake_id", ["intake_id"]),
        ("ix_clinical_safety_evaluations_outcome", ["outcome"]),
        (
            "ix_clinical_safety_evaluations_evaluated_by_user_id",
            ["evaluated_by_user_id"],
        ),
        ("ix_clinical_safety_evaluations_created_at", ["created_at"]),
    ):
        op.create_index(
            index_name,
            "clinical_safety_evaluations",
            columns,
            unique=False,
        )

    op.create_table(
        "clinical_safety_findings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("evaluation_id", sa.String(36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(36), nullable=False),
        sa.Column("rule_key", sa.String(100), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("rule_content_sha256", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("knowledge_fact_ids", sa.JSON(), nullable=False),
        sa.Column("condition_trace", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_clinical_safety_finding_order",
        ),
        sa.CheckConstraint(
            "rule_version >= 1",
            name="ck_clinical_safety_finding_rule_version",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'high', 'critical')",
            name="ck_clinical_safety_finding_severity",
        ),
        sa.CheckConstraint(
            "action IN ('document', 'review_before_proceeding', "
            "'urgent_clinical_review')",
            name="ck_clinical_safety_finding_action",
        ),
        sa.CheckConstraint(
            "length(rule_content_sha256) = 64",
            name="ck_clinical_safety_finding_rule_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["clinical_safety_evaluations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["clinical_safety_rules.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id",
            "sort_order",
            name="uq_clinical_safety_finding_order",
        ),
        sa.UniqueConstraint(
            "evaluation_id",
            "rule_id",
            name="uq_clinical_safety_finding_rule",
        ),
    )
    op.create_index(
        "ix_clinical_safety_findings_evaluation_id",
        "clinical_safety_findings",
        ["evaluation_id"],
        unique=False,
    )
    op.create_index(
        "ix_clinical_safety_findings_rule_id",
        "clinical_safety_findings",
        ["rule_id"],
        unique=False,
    )


def downgrade():
    # Rules and evaluations are clinical-governance and patient-safety records.
    # A routine rollback must never erase them.
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: clinical safety data cannot be checked."
        )
    connection = op.get_bind()
    counts = {
        table: connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in (
            "clinical_safety_findings",
            "clinical_safety_evaluations",
            "clinical_safety_rule_knowledge",
            "clinical_safety_rules",
        )
    }
    if any(counts.values()):
        raise RuntimeError(
            "Downgrade refused: clinical safety registry contains data."
        )

    op.drop_index(
        "ix_clinical_safety_findings_rule_id",
        table_name="clinical_safety_findings",
    )
    op.drop_index(
        "ix_clinical_safety_findings_evaluation_id",
        table_name="clinical_safety_findings",
    )
    op.drop_table("clinical_safety_findings")
    for index_name in (
        "ix_clinical_safety_evaluations_created_at",
        "ix_clinical_safety_evaluations_evaluated_by_user_id",
        "ix_clinical_safety_evaluations_outcome",
        "ix_clinical_safety_evaluations_intake_id",
        "ix_clinical_safety_evaluations_visit_id",
    ):
        op.drop_index(index_name, table_name="clinical_safety_evaluations")
    op.drop_table("clinical_safety_evaluations")
    op.drop_index(
        "ix_clinical_safety_rule_knowledge_medical_knowledge_fact_id",
        table_name="clinical_safety_rule_knowledge",
    )
    op.drop_index(
        "ix_clinical_safety_rule_knowledge_rule_id",
        table_name="clinical_safety_rule_knowledge",
    )
    op.drop_table("clinical_safety_rule_knowledge")
    for index_name in (
        "ix_clinical_safety_rules_reviewed_by_user_id",
        "ix_clinical_safety_rules_created_by_user_id",
        "ix_clinical_safety_rules_supersedes_rule_id",
        "ix_clinical_safety_rules_status",
        "ix_clinical_safety_rules_severity",
        "ix_clinical_safety_rules_clinical_domain",
        "ix_clinical_safety_rules_rule_key",
    ):
        op.drop_index(index_name, table_name="clinical_safety_rules")
    op.drop_table("clinical_safety_rules")
