"""enforce audit_logs append-only via trigger (no UPDATE/DELETE)

Revision ID: b4e8d3a7f2c9
Revises: a3f7c9e2d1b8
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b4e8d3a7f2c9"
down_revision: Union[str, None] = "a3f7c9e2d1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enforced via a trigger rather than REVOKE UPDATE/DELETE FROM
    # <role>: the app connects with a role name that varies by
    # environment (local docker-compose, Railway, etc.), so there is
    # no single fixed role to REVOKE from at migration time. A trigger
    # rejects the operation regardless of which role performs it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_logs is append-only: % is not permitted (row id=%)',
                TG_OP, OLD.id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs"
    )
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
