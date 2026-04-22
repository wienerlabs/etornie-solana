"""Add case_events table.

Revision ID: c0d1e2f3a4b5
Revises: b9d0e1f2c3a4
Create Date: 2026-04-22

Records each on-chain lifecycle event (status change, document upload,
closure, etc.) attested against a case. One row per update_case_
attestation tx; the case's current on-chain state is the latest event's
metadata_hash. Serves as a queryable cache for the dashboard's event
timeline; Solana tx logs remain the immutable source of truth.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c0d1e2f3a4b5"
down_revision = "b9d0e1f2c3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.SmallInteger(), nullable=False),
        sa.Column("tx_signature", sa.String(length=128), nullable=False),
        sa.Column("actor_wallet", sa.String(length=64), nullable=False),
        sa.Column("metadata_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_case_events_case_id",
        "case_events",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")
