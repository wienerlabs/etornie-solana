"""add users.evm_address for unified Solana + EVM identity (#74)

Stores the lowercase EVM address linked to an etornie account so a single
human keeps one handle across chains. Verified via EIP-191 signature.

Revision ID: c5a1e9d3f2b7
Revises: d4a5b6c7e8f9
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c5a1e9d3f2b7"
down_revision = "d4a5b6c7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("evm_address", sa.String(length=42), nullable=True),
    )
    op.create_index(
        "ix_users_evm_address", "users", ["evm_address"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_users_evm_address", table_name="users")
    op.drop_column("users", "evm_address")
