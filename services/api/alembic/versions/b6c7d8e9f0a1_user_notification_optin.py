"""Add opt-in notification fields to users.

Lets a user supply an explicit ``notification_email`` (separate from
the login ``email``) and toggle ``email_notifications_enabled`` so we
only send Stripe receipts / EUIPO submission updates / refund
confirmations to people who actively opted in. Wallet-only users
(who never give us an email at signup) can fill this in later from
their settings page.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notification_email",
            sa.String(length=255),
            nullable=True,
            comment=(
                "Optional dedicated address for product notifications. "
                "Wallet-only users fill this in to receive Stripe receipts, "
                "EUIPO submission updates, refund confirmations, etc. When "
                "NULL we fall back to ``email`` if available."
            ),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "Master opt-in toggle. False (default) means no automated "
                "emails leave the system for this user, regardless of "
                "``notification_email`` being set."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "email_notifications_enabled")
    op.drop_column("users", "notification_email")
