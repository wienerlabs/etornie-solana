"""add TOTP two-factor columns to users

Adds the storage for RFC 6238 TOTP two-factor authentication:
``totp_secret`` (base32 secret encrypted at rest), ``totp_enabled``
(flips true once the user proves possession with a valid code) and
``totp_recovery_codes`` (JSON array of bcrypt-hashed single-use codes).

Revision ID: c3f1a9b27e64
Revises: c5a1e9d3f2b7
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3f1a9b27e64"
down_revision = "c5a1e9d3f2b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("totp_recovery_codes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
