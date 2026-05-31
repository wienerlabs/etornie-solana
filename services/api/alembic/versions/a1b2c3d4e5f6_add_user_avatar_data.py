"""add users.avatar_data for DB-stored profile pictures

Stores profile-picture bytes in the database so avatars survive container
restarts and redeploys on ephemeral hosting (the previous on-disk location
under upload_dir/avatars was wiped on each deploy). avatar_path stays for the
legacy on-disk fallback.

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
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
