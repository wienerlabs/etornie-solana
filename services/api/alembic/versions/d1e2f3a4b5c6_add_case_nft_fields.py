"""Add case NFT fields.

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-04-22

Adds NFT lifecycle columns to cases for the soul-bound Token-2022
Case NFT: nft_mint (base58 pubkey), nft_state (enum), nft_setup_tx,
nft_mint_tx, nft_burn_tx (devnet signatures), nft_burned_at.

The NFT state machine:
    none              -- no mint attempted
    pending_claim     -- setup tx done, mint + extensions created, waiting for client
    minted            -- client claimed, NFT in client wallet (frozen)
    burned            -- case closed, NFT burned via permanent delegate
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    nft_state = sa.Enum(
        "none",
        "pending_claim",
        "minted",
        "burned",
        name="case_nft_state",
    )
    nft_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "cases",
        sa.Column("nft_mint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column(
            "nft_state",
            nft_state,
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "cases",
        sa.Column("nft_setup_tx", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column("nft_mint_tx", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column("nft_burn_tx", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column(
            "nft_burned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("cases", "nft_burned_at")
    op.drop_column("cases", "nft_burn_tx")
    op.drop_column("cases", "nft_mint_tx")
    op.drop_column("cases", "nft_setup_tx")
    op.drop_column("cases", "nft_state")
    op.drop_column("cases", "nft_mint")
    sa.Enum(name="case_nft_state").drop(op.get_bind(), checkfirst=True)
