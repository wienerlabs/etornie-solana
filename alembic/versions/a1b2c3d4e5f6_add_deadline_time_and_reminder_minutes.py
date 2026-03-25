"""add deadline_time to cases and reminder_minutes to agent_configs

Revision ID: a1b2c3d4e5f6
Revises: c5d6568a0a50
Create Date: 2026-03-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c5d6568a0a50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('deadline_time', sa.Time(), nullable=True))
    op.add_column(
        'agent_configs',
        sa.Column('reminder_minutes', sa.String(length=100), nullable=False, server_default='30,10,5,1'),
    )


def downgrade() -> None:
    op.drop_column('agent_configs', 'reminder_minutes')
    op.drop_column('cases', 'deadline_time')
