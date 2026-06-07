"""add organization Stripe subscription fields

Adds the billing source-of-truth columns that drive ``organizations.plan``
for the recurring subscription lane (issue #62): Stripe customer +
subscription ids, the mirrored subscription status, the active price id,
the current period end, and the cancel-at-period-end flag.

Revision ID: 98ee72c0f678
Revises: d4a5b6c7e8f9
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "98ee72c0f678"
down_revision = "914ad2096e71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_subscription_id", sa.String(length=255), nullable=True
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("subscription_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "subscription_price_id", sa.String(length=255), nullable=True
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "subscription_current_period_end",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "subscription_cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_unique_constraint(
        "uq_organizations_stripe_customer_id",
        "organizations",
        ["stripe_customer_id"],
    )
    op.create_unique_constraint(
        "uq_organizations_stripe_subscription_id",
        "organizations",
        ["stripe_subscription_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_organizations_stripe_subscription_id",
        "organizations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_organizations_stripe_customer_id",
        "organizations",
        type_="unique",
    )
    op.drop_column("organizations", "subscription_cancel_at_period_end")
    op.drop_column("organizations", "subscription_current_period_end")
    op.drop_column("organizations", "subscription_price_id")
    op.drop_column("organizations", "subscription_status")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
