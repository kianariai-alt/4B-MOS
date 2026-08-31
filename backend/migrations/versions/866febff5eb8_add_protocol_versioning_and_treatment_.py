"""add protocol versioning and treatment link

Revision ID: 866febff5eb8
Revises: 0f68a44361b0
Create Date: 2026-08-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "866febff5eb8"
down_revision: Union[str, Sequence[str], None] = "0f68a44361b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table(
        "protocol_templates",
        schema=None,
    ) as batch_op:
        batch_op.drop_index(
            batch_op.f("ix_protocol_templates_code")
        )

        batch_op.create_index(
            batch_op.f("ix_protocol_templates_code"),
            ["code"],
            unique=False,
        )

        batch_op.create_unique_constraint(
            "uq_protocol_templates_code_version",
            ["code", "version"],
        )

    with op.batch_alter_table(
        "treatments",
        schema=None,
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "protocol_template_id",
                sa.String(length=36),
                nullable=True,
            )
        )

        batch_op.add_column(
            sa.Column(
                "protocol_version",
                sa.String(length=30),
                nullable=True,
            )
        )

        batch_op.create_index(
            batch_op.f(
                "ix_treatments_protocol_template_id"
            ),
            ["protocol_template_id"],
            unique=False,
        )

        batch_op.create_foreign_key(
            "fk_treatments_protocol_template_id",
            "protocol_templates",
            ["protocol_template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "treatments",
        schema=None,
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_treatments_protocol_template_id",
            type_="foreignkey",
        )

        batch_op.drop_index(
            batch_op.f(
                "ix_treatments_protocol_template_id"
            )
        )

        batch_op.drop_column(
            "protocol_version"
        )

        batch_op.drop_column(
            "protocol_template_id"
        )

    with op.batch_alter_table(
        "protocol_templates",
        schema=None,
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_protocol_templates_code_version",
            type_="unique",
        )

        batch_op.drop_index(
            batch_op.f(
                "ix_protocol_templates_code"
            )
        )

        batch_op.create_index(
            batch_op.f(
                "ix_protocol_templates_code"
            ),
            ["code"],
            unique=True,
        )