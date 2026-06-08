"""add GDPR erasure tombstone columns to users

Adds ``erased_at`` (set when the user row has been anonymised under
GDPR Article 17) and ``erasure_reason`` (audit note of who/why).

Revision ID: e7b2d4f1a9c3
Revises: d4a5b6c7e8f9
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e7b2d4f1a9c3"
down_revision = "c3f1a9b27e64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("erasure_reason", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "erasure_reason")
    op.drop_column("users", "erased_at")
