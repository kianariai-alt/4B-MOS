"""Add immutable pilot launch packages.

Revision ID: f2c6b8d1a704
Revises: e9f4a2b7c613
"""

from alembic import context, op
import sqlalchemy as sa


revision = "f2c6b8d1a704"
down_revision = "e9f4a2b7c613"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pilot_launch_packages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("release_ref", sa.String(200), nullable=False),
        sa.Column("readiness_sha256", sa.String(64), nullable=False),
        sa.Column("attestation_manifest", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(readiness_sha256) = 64",
            name="ck_pilot_launch_package_readiness_sha256",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name="ck_pilot_launch_package_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_ref",
            name="uq_pilot_launch_package_release_ref",
        ),
    )
    op.create_index(
        "ix_pilot_launch_packages_release_ref",
        "pilot_launch_packages",
        ["release_ref"],
        unique=False,
    )
    op.create_index(
        "ix_pilot_launch_packages_created_by_user_id",
        "pilot_launch_packages",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_pilot_launch_packages_created_at",
        "pilot_launch_packages",
        ["created_at"],
        unique=False,
    )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "Offline downgrade refused: pilot launch packages cannot be checked."
        )
    connection = op.get_bind()
    package_count = connection.scalar(
        sa.text("SELECT count(*) FROM pilot_launch_packages")
    )
    if package_count:
        raise RuntimeError(
            "Downgrade refused: pilot launch package history exists."
        )
    op.drop_index(
        "ix_pilot_launch_packages_created_at",
        table_name="pilot_launch_packages",
    )
    op.drop_index(
        "ix_pilot_launch_packages_created_by_user_id",
        table_name="pilot_launch_packages",
    )
    op.drop_index(
        "ix_pilot_launch_packages_release_ref",
        table_name="pilot_launch_packages",
    )
    op.drop_table("pilot_launch_packages")
