"""add avatar columns to users

Adds ``avatar_path`` (server-side absolute path) and ``avatar_mime``
(content-type) so the profile page can let users upload a profile
picture. The bytes themselves stay on disk under
``<upload_dir>/avatars/<user_id>.<ext>`` — only the path + mime go to
the database so the column never exceeds the standard 1 KB row size.

Revision ID: d2e3f4a5b6c8
Revises: c1d2e3f4a5b6
Create Date: 2026-05-02 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c8"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_path", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("avatar_mime", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_mime")
    op.drop_column("users", "avatar_path")
