"""Add case attestation fields.

Revision ID: a8c9d0e1f2b3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-22

Adds attestation_tx (Solana devnet tx signature) and attestation_pda
(program-derived address) columns to cases. Populated after the backend
submits a create_case_attestation instruction for a new case whose
creator has a wallet_address.
"""

from alembic import op
import sqlalchemy as sa


revision = "a8c9d0e1f2b3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("attestation_tx", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column("attestation_pda", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cases", "attestation_pda")
    op.drop_column("cases", "attestation_tx")
