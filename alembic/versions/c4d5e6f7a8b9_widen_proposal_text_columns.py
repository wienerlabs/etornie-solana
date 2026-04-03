"""Widen proposal columns and add rejection_reason.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-04

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "proposals",
        "madrid_system",
        existing_type=sa.String(50),
        type_=sa.Text(),
    )
    op.alter_column(
        "proposals",
        "national_application",
        existing_type=sa.String(50),
        type_=sa.Text(),
    )
    op.add_column(
        "proposals",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proposals", "rejection_reason")
    op.alter_column(
        "proposals",
        "madrid_system",
        existing_type=sa.Text(),
        type_=sa.String(50),
    )
    op.alter_column(
        "proposals",
        "national_application",
        existing_type=sa.Text(),
        type_=sa.String(50),
    )
