"""Add operator_key_access_log for operator key audit trail.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_key_access_log",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("caller_context", sa.String(255), nullable=False),
        sa.Column("op_kind", sa.String(20), nullable=False),
        sa.Column(
            "success",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("note", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_operator_key_access_log_accessed_at",
        "operator_key_access_log",
        ["accessed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operator_key_access_log_accessed_at",
        table_name="operator_key_access_log",
    )
    op.drop_table("operator_key_access_log")
