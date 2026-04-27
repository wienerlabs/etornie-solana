"""Add Solana payment fields to ukipo_submissions.

Revision ID: a9c0d1e2f3b4
Revises: f8b9c0d1e2f3
Create Date: 2026-04-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c0d1e2f3b4"
down_revision: Union[str, None] = "f8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_payment_tx", sa.String(128), nullable=True),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_payer_wallet", sa.String(64), nullable=True),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_payment_lamports", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column(
            "solana_payment_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ukipo_submissions", "solana_payment_at")
    op.drop_column("ukipo_submissions", "solana_payment_lamports")
    op.drop_column("ukipo_submissions", "solana_payer_wallet")
    op.drop_column("ukipo_submissions", "solana_payment_tx")
