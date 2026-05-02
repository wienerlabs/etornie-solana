"""remove the lawyer role layer

Etornie originally shipped a traditional attorney/client model. The
platform now files directly through the official IP offices (UKIPO,
EUIPO, WIPO, IP Australia, …) via the EtornieGPT agent, so a separate
``lawyer`` user identity is no longer meaningful.

This migration is data-only:

* re-points existing ``lawyer`` users to either ``admin`` (the
  platform owner — kept administrative access on purpose) or
  ``client`` (the rest, who become regular consumers of EtornieGPT).
* nulls every ``cases.assigned_lawyer_id`` so the now-orphaned column
  no longer points at users whose role has changed.

The Postgres ``user_role`` enum value ``'lawyer'`` is **not** dropped;
historical Alembic state still references it and dropping enum values
is destructive. The Python ``UserRole`` enum drops ``lawyer`` in code
so no new row will ever take that value.

A follow-up migration can remove the ``cases.assigned_lawyer_id``
column entirely once nothing reads it. It is left here for now so
``docs/REMOVED_LAWYER_LAYER.md`` can be cross-checked against the
exact data we touched.

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a7
Create Date: 2026-05-02 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b1c2d3e4f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_USER_ID = "b33506d1-e8fa-43da-8ec6-3eae1c780ba7"  # makinci473@gmail.com


def upgrade() -> None:
    # Promote the platform owner so they keep admin access after the
    # role collapse. Other lawyers become regular clients.
    op.execute(
        f"UPDATE users SET role='admin' WHERE id='{_OWNER_USER_ID}' AND role='lawyer'"
    )
    op.execute(
        "UPDATE users SET role='client' WHERE role='lawyer'"
    )
    # Drop every dangling assigned_lawyer_id so no case row points at a
    # user whose role just changed. The column itself stays — a later
    # migration can drop it once all readers are retired.
    op.execute(
        "UPDATE cases SET assigned_lawyer_id=NULL WHERE assigned_lawyer_id IS NOT NULL"
    )


def downgrade() -> None:
    # Best-effort restore: turn the platform owner back into a lawyer.
    # The other three users' original role was also `lawyer`, but we
    # cannot tell them apart from clients post-collapse without an
    # external snapshot — see docs/REMOVED_LAWYER_LAYER.md for the
    # full list of IDs that were `lawyer` at removal time.
    op.execute(
        f"UPDATE users SET role='lawyer' WHERE id='{_OWNER_USER_ID}'"
    )
