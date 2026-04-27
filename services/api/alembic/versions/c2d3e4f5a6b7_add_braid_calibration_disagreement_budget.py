"""Add bounded-learning Phase 2.5 tables: calibration, disagreement, budget.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE braid_calibration_events (
            id UUID PRIMARY KEY,
            decision_id UUID NOT NULL REFERENCES braid_decisions(id) ON DELETE CASCADE,
            capability_name VARCHAR(128) NOT NULL,
            stated_confidence DOUBLE PRECISION,
            actual_outcome BOOLEAN NOT NULL,
            log_update DOUBLE PRECISION,
            reward DOUBLE PRECISION,
            feedback_source VARCHAR(32) NOT NULL,
            feedback_user_id UUID REFERENCES users(id),
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_braid_calibration_events_decision_id",
        "braid_calibration_events",
        ["decision_id"],
    )
    op.create_index(
        "ix_braid_calibration_events_capability_name",
        "braid_calibration_events",
        ["capability_name"],
    )

    op.execute("""
        CREATE TABLE braid_disagreement_observations (
            id UUID PRIMARY KEY,
            capability_name VARCHAR(128) NOT NULL,
            grouping_key VARCHAR(256) NOT NULL,
            sample_count INTEGER NOT NULL,
            mean DOUBLE PRECISION NOT NULL,
            std_dev DOUBLE PRECISION NOT NULL,
            coefficient_of_variation DOUBLE PRECISION NOT NULL,
            escalation_triggered BOOLEAN NOT NULL DEFAULT FALSE,
            escalation_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.6,
            decision_ids JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index(
        "ix_braid_disagreement_observations_grouping_key",
        "braid_disagreement_observations",
        ["grouping_key"],
    )
    op.create_index(
        "ix_braid_disagreement_observations_capability_name",
        "braid_disagreement_observations",
        ["capability_name"],
    )

    op.execute("""
        CREATE TABLE braid_budget_state (
            id UUID PRIMARY KEY,
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL,
            daily_call_budget INTEGER NOT NULL DEFAULT 1000,
            calls_used INTEGER NOT NULL DEFAULT 0,
            calls_skipped_under_pressure INTEGER NOT NULL DEFAULT 0,
            skip_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.2,
            pressure_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.8,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.drop_table("braid_budget_state")
    op.drop_table("braid_disagreement_observations")
    op.drop_table("braid_calibration_events")
