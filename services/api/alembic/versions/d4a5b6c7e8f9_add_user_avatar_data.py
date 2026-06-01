"""add users.avatar_data for DB-stored profile pictures

Stores profile-picture bytes in the database so avatars survive container
restarts and redeploys on ephemeral hosting (the previous on-disk location
under upload_dir/avatars was wiped on each deploy). avatar_path stays for the
legacy on-disk fallback.

Revision ID: d4a5b6c7e8f9
Revises: f6a7b8c9d0e1
Create Date: 2026-06-01

NOTE: this migration originally shared the revision id ``a1b2c3d4e5f6``
with ``a1b2c3d4e5f6_add_deadline_time_and_reminder_minutes`` further up
the chain. The duplicate id made Alembic report a cycle and refuse to
run (``alembic upgrade`` failed in the Railway pre-deploy step). It was
given a unique id; it is the head and nothing references it as a parent,
so no other migration changed.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4a5b6c7e8f9"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_data", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_data")
