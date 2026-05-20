"""Add euipo_oauth_token table for persistent EUIPO user-flow credentials.

EUIPO's filing/portfolio APIs use the OAuth2 authorization_code flow.
Without persisting the refresh_token, every server restart wipes the
session and the Stripe auto-submit path raises ``"No EUIPO user
session"``. Storing a single operator-wide row (singleton) keeps the
session alive across deployments — re-auth only needed when the
refresh_token itself expires.

Revision ID: e3f4a5b6c7d9
Revises: d2e3f4a5b6c8
Create Date: 2026-05-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d9"
down_revision = "d2e3f4a5b6c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "euipo_oauth_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "scope",
            sa.Text(),
            nullable=True,
            comment="Space-separated OIDC scopes granted by EUIPO.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        # Operator-wide singleton — the EUIPO API call is made from the
        # backend operator identity, not per end-user. Enforce by
        # constraining the row to id=1.
        sa.CheckConstraint("id = 1", name="ck_euipo_oauth_token_singleton"),
    )


def downgrade() -> None:
    op.drop_table("euipo_oauth_token")
