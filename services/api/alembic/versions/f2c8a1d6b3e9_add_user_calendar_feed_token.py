"""add users.calendar_feed_token for ICS calendar subscription feed

Stores the unguessable token that authorises the read-only iCalendar
feed of a user's case deadlines and renewals
(GET /calendar/feed/<token>.ics). Null until the user enables the feed.

Revision ID: f2c8a1d6b3e9
Revises: d4a5b6c7e8f9
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f2c8a1d6b3e9"
down_revision = "e7b2d4f1a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("calendar_feed_token", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_users_calendar_feed_token",
        "users",
        ["calendar_feed_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_calendar_feed_token", table_name="users")
    op.drop_column("users", "calendar_feed_token")
