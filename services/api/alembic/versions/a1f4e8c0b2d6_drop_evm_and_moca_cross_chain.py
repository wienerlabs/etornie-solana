"""drop EVM unified-identity + Moca cross-chain columns (Solana-only pivot)

Reverts the unified-identity (#74) and per-case chain-routing (#73) schema.
Removes ``users.evm_address`` and the ``cases`` columns ``chain_routing`` /
``moca_status`` / ``moca_attestation_tx`` plus their enum types. Etornie is
Solana-only: no EVM wallet linkage and no Moca attestation routing.

Revision ID: a1f4e8c0b2d6
Revises: 98ee72c0f678
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1f4e8c0b2d6"
down_revision = "98ee72c0f678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # EVM unified identity (#74)
    op.drop_index("ix_users_evm_address", table_name="users")
    op.drop_column("users", "evm_address")

    # Moca per-case chain routing (#73)
    op.drop_column("cases", "moca_attestation_tx")
    op.drop_column("cases", "moca_status")
    op.drop_column("cases", "chain_routing")
    sa.Enum(name="moca_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="chain_routing").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Recreate Moca per-case chain routing (#73)
    chain_routing = sa.Enum("solana", "moca", "both", name="chain_routing")
    moca_status = sa.Enum(
        "not_routed", "pending", "written", "failed", name="moca_status"
    )
    bind = op.get_bind()
    chain_routing.create(bind, checkfirst=True)
    moca_status.create(bind, checkfirst=True)
    op.add_column(
        "cases",
        sa.Column(
            "chain_routing", chain_routing, nullable=False, server_default="solana"
        ),
    )
    op.add_column(
        "cases",
        sa.Column(
            "moca_status", moca_status, nullable=False, server_default="not_routed"
        ),
    )
    op.add_column(
        "cases",
        sa.Column("moca_attestation_tx", sa.String(length=128), nullable=True),
    )

    # Recreate EVM unified identity (#74)
    op.add_column(
        "users", sa.Column("evm_address", sa.String(length=42), nullable=True)
    )
    op.create_index(
        "ix_users_evm_address", "users", ["evm_address"], unique=True
    )
