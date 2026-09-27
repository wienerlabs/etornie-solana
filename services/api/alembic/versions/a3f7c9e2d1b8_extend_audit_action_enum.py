"""extend audit_action enum with case/document/notification mutation types

Revision ID: a3f7c9e2d1b8
Revises: d7f3a9c1e4b2
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a3f7c9e2d1b8"
down_revision: Union[str, None] = "d7f3a9c1e4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New AuditAction values added for issue #30 (finish + enforce the
# existing audit log). Follows the same pattern as the earlier
# ``ALTER TYPE document_status ADD VALUE`` in
# a2b3c4d5e6f7_add_cancellation_and_audit_log.py.
_NEW_VALUES = (
    "case_created",
    "case_updated",
    "case_status_changed",
    "document_created",
    "document_updated",
    "document_deleted",
    "notification_created",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ``ALTER TYPE ... DROP VALUE``. Removing enum
    # values safely requires rebuilding the type (rename old type,
    # create new type with the reduced value set, cast the column
    # over, drop the old type) and is deliberately not implemented
    # here — the same posture the original audit_action migration
    # would face if it needed to remove a value. Downgrading past
    # this migration while any row uses one of the new values will
    # fail at the application layer, not at this migration.
    pass
