"""add commission to trade_memories

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-02-18 02:10:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trade_memories', sa.Column('commission', sa.Float(), nullable=True, comment='手续费 (USDT)'))


def downgrade() -> None:
    op.drop_column('trade_memories', 'commission')
