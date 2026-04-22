"""Add lawyer verification fields to users.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-19

Adds a verification layer on top of the existing role system:
- is_verified: boolean indicating the account has been vetted. For clients
  and admins this is always true (by convention and via backfill). For
  lawyers this defaults to false and must be flipped by an admin after
  reviewing the submitted bar credentials.
- bar_association: free-text name of the bar association the lawyer
  belongs to (e.g. "Istanbul Barosu", "California State Bar").
- bar_number: bar membership identifier the admin can check against the
  public registry.

Backfill policy:
- All existing non-lawyer rows are marked verified.
- Existing lawyer rows are left unverified so the admin has to explicitly
  confirm their credentials under the new regime. This is the safer
  default; flipping false to true manually is trivial.
"""

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    # Clients and admins are verified by convention.
    op.execute(
        "UPDATE users SET is_verified = TRUE "
        "WHERE role IN ('client', 'admin')"
    )


def downgrade() -> None:
    op.drop_column("users", "bar_number")
    op.drop_column("users", "bar_association")
    op.drop_column("users", "is_verified")
