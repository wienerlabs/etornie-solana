"""Add Stripe payment fields to ukipo_submissions.

Lets the UKIPO robot's awaiting_payment step accept a card payment via
Stripe alongside the existing x402 SOL flow. The Stripe PI id is the
correlation key webhook + reconcile use to advance the submission to
``filed``.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-05-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ukipo_submissions",
        sa.Column(
            "stripe_payment_intent_id", sa.String(length=128), nullable=True
        ),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column(
            "stripe_checkout_session_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column(
            "stripe_amount_minor",
            sa.BigInteger(),
            nullable=True,
            comment="Stripe-billed amount in the minor currency unit (pence for GBP).",
        ),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column(
            "stripe_currency", sa.String(length=10), nullable=True
        ),
    )
    op.add_column(
        "ukipo_submissions",
        sa.Column(
            "stripe_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ukipo_submissions_stripe_pi",
        "ukipo_submissions",
        ["stripe_payment_intent_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ukipo_submissions_stripe_pi",
        table_name="ukipo_submissions",
    )
    op.drop_column("ukipo_submissions", "stripe_confirmed_at")
    op.drop_column("ukipo_submissions", "stripe_currency")
    op.drop_column("ukipo_submissions", "stripe_amount_minor")
    op.drop_column("ukipo_submissions", "stripe_checkout_session_id")
    op.drop_column("ukipo_submissions", "stripe_payment_intent_id")
