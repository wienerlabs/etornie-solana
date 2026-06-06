"""add per-case chain routing policy columns (#73)

Adds ``chain_routing`` (solana | moca | both, default solana),
``moca_status`` (not_routed | pending | written | failed), and
``moca_attestation_tx`` to cases.

Revision ID: b8d3e5f29a14
Revises: d4a5b6c7e8f9
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b8d3e5f29a14"
down_revision = "d4a5b6c7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    chain_routing = sa.Enum(
        "solana", "moca", "both", name="chain_routing"
    )
    moca_status = sa.Enum(
        "not_routed", "pending", "written", "failed", name="moca_status"
    )
    bind = op.get_bind()
    chain_routing.create(bind, checkfirst=True)
    moca_status.create(bind, checkfirst=True)

    op.add_column(
        "cases",
        sa.Column(
            "chain_routing",
            chain_routing,
            nullable=False,
            server_default="solana",
        ),
    )
    op.add_column(
        "cases",
        sa.Column(
            "moca_status",
            moca_status,
            nullable=False,
            server_default="not_routed",
        ),
    )
    op.add_column(
        "cases",
        sa.Column("moca_attestation_tx", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cases", "moca_attestation_tx")
    op.drop_column("cases", "moca_status")
    op.drop_column("cases", "chain_routing")
    sa.Enum(name="moca_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="chain_routing").drop(op.get_bind(), checkfirst=True)
