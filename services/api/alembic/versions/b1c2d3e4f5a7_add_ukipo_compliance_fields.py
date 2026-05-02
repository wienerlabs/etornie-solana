"""add x402 compliance fields to ukipo_submissions

Adds the columns needed to bind a UKIPO filing payment to an on-chain
Groth16 compliance proof:
  * solana_query_hash_hex   — canonical filing-context query hash
  * solana_commitment_hex   — Poseidon commitment from public input[2]
  * solana_compliance_tx    — verify_compliance_proof tx signature
  * solana_compliance_pda   — ComplianceRecord PDA (base58)

The existing ``solana_payment_tx`` / ``solana_payer_wallet`` columns
stay; the new fields layer on top so the agent confirm-payment endpoint
can persist the full proof lineage in one row.

Revision ID: b1c2d3e4f5a7
Revises: a0b1c2d3e4f5
Create Date: 2026-05-02 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a7"
down_revision: Union[str, None] = "a0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_query_hash_hex", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_commitment_hex", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_compliance_tx", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column("solana_compliance_pda", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ukipo_submissions", "solana_compliance_pda")
    op.drop_column("ukipo_submissions", "solana_compliance_tx")
    op.drop_column("ukipo_submissions", "solana_commitment_hex")
    op.drop_column("ukipo_submissions", "solana_query_hash_hex")
