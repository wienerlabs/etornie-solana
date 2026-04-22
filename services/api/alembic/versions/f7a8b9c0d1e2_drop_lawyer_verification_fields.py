"""Drop lawyer verification fields.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-22

Reverses the previous lawyer-verification columns. The product decision
is to treat wallet sign-up as self-declared for the lawyer role, with
role restrictions (no admin self-assignment) and audit-ready records.
A cryptographically verifiable lawyer-identity flow will be reintroduced
later via a separate on-chain primitive, not via an admin approval flag.
"""

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "bar_number")
    op.drop_column("users", "bar_association")
    op.drop_column("users", "is_verified")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("bar_association", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("bar_number", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE users SET is_verified = TRUE WHERE role IN ('client', 'admin')"
    )
