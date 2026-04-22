"""Add case.client_wallet.

Revision ID: b9d0e1f2c3a4
Revises: a8c9d0e1f2b3
Create Date: 2026-04-22

Adds a nullable client_wallet column to cases. Populated from either the
linked user's wallet_address (existing client flow) or an explicit wallet
input (by-wallet flow). Anchored into the on-chain CaseAttestation PDA
as the second Pubkey argument of create_case_attestation.
"""

from alembic import op
import sqlalchemy as sa


revision = "b9d0e1f2c3a4"
down_revision = "a8c9d0e1f2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("client_wallet", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cases", "client_wallet")
