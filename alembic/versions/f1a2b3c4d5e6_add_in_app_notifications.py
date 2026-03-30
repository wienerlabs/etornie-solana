"""add in_app_notifications table

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-03-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE in_app_notification_type AS ENUM ("
        "'document_uploaded', 'document_approved', 'document_rejected', "
        "'note_added', 'case_updated', 'case_created'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    op.execute("""
        CREATE TABLE in_app_notifications (
            id UUID PRIMARY KEY,
            recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            sender_id UUID REFERENCES users(id) ON DELETE SET NULL,
            notification_type in_app_notification_type NOT NULL,
            title VARCHAR(500) NOT NULL,
            message TEXT NOT NULL,
            case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
            is_read BOOLEAN NOT NULL DEFAULT false,
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index("ix_in_app_notifications_recipient_id", "in_app_notifications", ["recipient_id"])
    op.create_index("ix_in_app_notifications_is_read", "in_app_notifications", ["recipient_id", "is_read"])


def downgrade() -> None:
    op.drop_table("in_app_notifications")
    op.execute("DROP TYPE IF EXISTS in_app_notification_type")
