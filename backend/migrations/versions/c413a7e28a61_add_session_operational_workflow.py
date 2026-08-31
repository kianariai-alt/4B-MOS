"""add session operational workflow

Revision ID: c413a7e28a61
Revises: 85f2c25ec4c1
Create Date: 2026-08-31 17:11:58.099865
"""

from alembic import op
import sqlalchemy as sa


revision = "c413a7e28a61"
down_revision = "85f2c25ec4c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "treatment_sessions",
        sa.Column(
            "operational_status",
            sa.String(length=30),
            nullable=False,
            server_default="scheduled",
        ),
    )

    op.create_index(
        "ix_treatment_sessions_operational_status",
        "treatment_sessions",
        ["operational_status"],
        unique=False,
    )

    op.add_column(
        "treatment_sessions",
        sa.Column(
            "checked_in_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "treatment_sessions",
        sa.Column(
            "ready_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "treatment_sessions",
        sa.Column(
            "discharged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "treatment_sessions",
        "discharged_at",
    )

    op.drop_column(
        "treatment_sessions",
        "ready_at",
    )

    op.drop_column(
        "treatment_sessions",
        "checked_in_at",
    )

    op.drop_index(
        "ix_treatment_sessions_operational_status",
        table_name="treatment_sessions",
    )

    op.drop_column(
        "treatment_sessions",
        "operational_status",
    )