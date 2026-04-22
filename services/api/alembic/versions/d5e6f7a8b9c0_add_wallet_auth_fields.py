"""Add wallet authentication fields to users.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-19

Adds Solana wallet authentication support:
- wallet_address: base58 Solana pubkey (32-44 chars), unique, nullable
- public_handle: short human-readable identifier (etornie_<8char>), unique, nullable
- auth_method: one of email | wallet | both
- Relaxes email and hashed_password to nullable so wallet-only users can exist
- CHECK constraint enforces that a user is authenticatable
  (email + hashed_password set, OR wallet_address set)
"""

from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("wallet_address", sa.String(length=44), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("public_handle", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_method",
            sa.String(length=16),
            nullable=False,
            server_default="email",
        ),
    )

    op.create_unique_constraint(
        "uq_users_wallet_address", "users", ["wallet_address"]
    )
    op.create_unique_constraint(
        "uq_users_public_handle", "users", ["public_handle"]
    )
    op.create_index(
        "ix_users_wallet_address", "users", ["wallet_address"], unique=False
    )
    op.create_index(
        "ix_users_public_handle", "users", ["public_handle"], unique=False
    )

    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column(
        "users", "hashed_password", existing_type=sa.String(255), nullable=True
    )

    op.create_check_constraint(
        "ck_users_auth_method_values",
        "users",
        "auth_method IN ('email', 'wallet', 'both')",
    )
    op.create_check_constraint(
        "ck_users_authenticatable",
        "users",
        "(email IS NOT NULL AND hashed_password IS NOT NULL) "
        "OR wallet_address IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_authenticatable", "users", type_="check")
    op.drop_constraint("ck_users_auth_method_values", "users", type_="check")

    op.alter_column(
        "users", "hashed_password", existing_type=sa.String(255), nullable=False
    )
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)

    op.drop_index("ix_users_public_handle", table_name="users")
    op.drop_index("ix_users_wallet_address", table_name="users")
    op.drop_constraint("uq_users_public_handle", "users", type_="unique")
    op.drop_constraint("uq_users_wallet_address", "users", type_="unique")

    op.drop_column("users", "auth_method")
    op.drop_column("users", "public_handle")
    op.drop_column("users", "wallet_address")
