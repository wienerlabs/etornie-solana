"""add guest client fields to cases

Revision ID: b7e8f9a0c1d2
Revises: 34d6de2c0667
Create Date: 2026-03-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e8f9a0c1d2'
down_revision: Union[str, None] = '34d6de2c0667'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make client_id nullable
    with op.batch_alter_table('cases') as batch_op:
        batch_op.alter_column(
            'client_id',
            existing_type=sa.Uuid(),
            nullable=True,
        )
    # Add guest client columns
    op.add_column('cases', sa.Column('guest_client_name', sa.String(255), nullable=True))
    op.add_column('cases', sa.Column('guest_client_email', sa.String(255), nullable=True))
    op.add_column('cases', sa.Column('guest_client_phone', sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'guest_client_phone')
    op.drop_column('cases', 'guest_client_email')
    op.drop_column('cases', 'guest_client_name')
    with op.batch_alter_table('cases') as batch_op:
        batch_op.alter_column(
            'client_id',
            existing_type=sa.Uuid(),
            nullable=False,
        )
