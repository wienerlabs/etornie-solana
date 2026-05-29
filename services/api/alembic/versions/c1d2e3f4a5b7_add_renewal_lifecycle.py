"""Add trademark renewal lifecycle: case.renewal_due_at + RenewalReminder table.

EUIPO trademarks are renewable indefinitely for 10-year periods. We
stamp ``cases.renewal_due_at`` at promotion time (filing_date + 10y)
and re-stamp it on each successful renewal. A separate
``renewal_reminder`` table records every email/in-app reminder so
the nightly dispatcher cannot double-fire on the same 90-day or
30-day window.

Revision ID: c1d2e3f4a5b7
Revises: b6c7d8e9f0a1
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b7"
down_revision: str | None = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column(
            "renewal_due_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "cases",
        sa.Column(
            "last_renewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_cases_renewal_due_at",
        "cases",
        ["renewal_due_at"],
    )
    op.create_table(
        "renewal_reminder",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "case_id",
            sa.UUID(),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # ``window_days`` records WHICH reminder bucket fired (90, 30,
        # or 0 days before renewal_due_at). Combined with case_id the
        # row enforces "one reminder per window per case" via the
        # unique constraint below.
        sa.Column("window_days", sa.Integer(), nullable=False),
        # Snapshot of the renewal_due_at at the moment the reminder
        # was sent — lets us audit which target date the reminder was
        # for, so a later renewal that re-stamps renewal_due_at does
        # not break the per-window dedup.
        sa.Column(
            "target_due_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Channels the reminder was delivered through. Each entry is
        # one of "email", "in_app". The dispatcher writes both
        # whenever a recipient has opted into email.
        sa.Column(
            "channels",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.UniqueConstraint(
            "case_id",
            "window_days",
            "target_due_at",
            name="uq_renewal_reminder_case_window_target",
        ),
    )
    op.create_index(
        "ix_renewal_reminder_case_id",
        "renewal_reminder",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_renewal_reminder_case_id", table_name="renewal_reminder"
    )
    op.drop_table("renewal_reminder")
    op.drop_index("ix_cases_renewal_due_at", table_name="cases")
    op.drop_column("cases", "last_renewed_at")
    op.drop_column("cases", "renewal_due_at")
