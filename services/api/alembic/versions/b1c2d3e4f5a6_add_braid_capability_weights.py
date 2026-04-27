"""Add braid_capability_weights table for bounded online learning.

Revision ID: b1c2d3e4f5a6
Revises: a9c0d1e2f3b4
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9c0d1e2f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE braid_capability_weights (
            id UUID PRIMARY KEY,
            capability_name VARCHAR(128) UNIQUE NOT NULL,
            weight DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            weight_floor DOUBLE PRECISION NOT NULL DEFAULT 0.05,
            weight_ceiling DOUBLE PRECISION NOT NULL DEFAULT 0.95,
            successes BIGINT NOT NULL DEFAULT 0,
            failures BIGINT NOT NULL DEFAULT 0,
            last_decision_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_braid_capability_weights_capability_name",
        "braid_capability_weights",
        ["capability_name"],
    )


def downgrade() -> None:
    op.drop_table("braid_capability_weights")
