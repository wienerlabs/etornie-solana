"""audit_logs: actor_type, nullable actor_id, notification actions, case FK

Revision ID: c8a1d5e9f3b2
Revises: b4e8d3a7f2c9
Create Date: 2026-11-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8a1d5e9f3b2"
down_revision: Union[str, None] = "b4e8d3a7f2c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_VALUES = (
    "notification_updated",
    "notification_cancelled",
    "notification_sent",
    "notification_failed",
    "in_app_notification_created",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    # None of these statements touches existing rows, so the append-only
    # trigger (BEFORE UPDATE OR DELETE ... FOR EACH ROW) never fires:
    # ADD COLUMN with a constant default is a catalog change, DROP NOT NULL
    # and the FK swap are DDL.
    op.add_column(
        "audit_logs",
        sa.Column(
            "actor_type",
            sa.String(20),
            nullable=False,
            server_default="user",
        ),
    )
    op.alter_column(
        "audit_logs", "actor_id", existing_type=sa.Uuid(), nullable=True
    )

    # The original table was created with raw SQL, so Postgres named the
    # inline FK audit_logs_case_id_fkey. ON DELETE SET NULL would be an
    # UPDATE on audit_logs, which the trigger rejects.
    op.execute(
        "ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_case_id_fkey"
    )
    op.create_foreign_key(
        "fk_audit_logs_case_id_cases",
        "audit_logs",
        "cases",
        ["case_id"],
        ["id"],
    )


def downgrade() -> None:
    # Postgres cannot drop enum values, and actor_id stays nullable: rows
    # written by system actors have no user, so NOT NULL cannot come back
    # while they exist (and the append-only trigger forbids deleting them).
    op.drop_constraint("fk_audit_logs_case_id_cases", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_case_id_fkey",
        "audit_logs",
        "cases",
        ["case_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("audit_logs", "actor_type")
