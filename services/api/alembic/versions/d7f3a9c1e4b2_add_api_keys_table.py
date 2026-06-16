"""add api_keys table for the public partner Q&A API

Stores partner API keys (SHA-256 hash only) for the answer-only public
chat endpoint. No plaintext is persisted.

Revision ID: d7f3a9c1e4b2
Revises: a1f4e8c0b2d6
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d7f3a9c1e4b2"
down_revision = "a1f4e8c0b2d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "rate_limit_per_minute",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index(
        op.f("ix_api_keys_key_hash"),
        "api_keys",
        ["key_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_table("api_keys")
