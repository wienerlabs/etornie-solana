"""Add braid_decisions table for BRAID agent audit trail.

Revision ID: e4f5a6b7c8d9
Revises: d3f4a5b6c7d8
Create Date: 2026-04-26

Stores one row per BRAID capability invocation so every reasoning step
is auditable. Each row binds the OpenServ workspace + thread context to
the capability that ran, the args BRAID extracted from the user's
message, the result we returned, and timing data.

Columns:
    workspace_id      : OpenServ workspace UUID (string)
    thread_id         : OpenServ chat thread within the workspace
    agent_id          : OpenServ agent id that received the request
    agent_name        : human-readable agent name (denormalized for audit)
    capability_name   : name of the capability invoked (e.g. ping)
    args              : JSON of capability inputs after Zod validation
    result            : JSON of capability output, null on error
    error             : error message, null on success
    user_message      : the raw user chat text that triggered this run
    started_at        : monotonic start time
    completed_at      : monotonic end time
    duration_ms       : completed_at - started_at
    created_at        : DB insert timestamp (server default now())
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e4f5a6b7c8d9"
down_revision = "d3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "braid_decisions",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(128), nullable=True),
        sa.Column("capability_name", sa.String(128), nullable=False),
        sa.Column(
            "args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_braid_decisions_workspace_thread",
        "braid_decisions",
        ["workspace_id", "thread_id", "started_at"],
    )
    op.create_index(
        "ix_braid_decisions_capability_name",
        "braid_decisions",
        ["capability_name", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_braid_decisions_capability_name", table_name="braid_decisions"
    )
    op.drop_index(
        "ix_braid_decisions_workspace_thread", table_name="braid_decisions"
    )
    op.drop_table("braid_decisions")
