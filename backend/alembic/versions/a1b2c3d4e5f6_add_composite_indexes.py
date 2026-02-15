"""add composite indexes for positions and orders

Revision ID: a1b2c3d4e5f6
Revises: f4dd271299aa
Create Date: 2026-02-15

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f4dd271299aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Position 复合索引
    op.create_index('ix_position_user_status', 'positions', ['user_id', 'status'])
    op.create_index('ix_position_user_symbol_status', 'positions', ['user_id', 'symbol', 'status'])
    
    # Order 复合索引
    op.create_index('ix_order_user_status', 'orders', ['user_id', 'status'])
    op.create_index('ix_order_user_symbol', 'orders', ['user_id', 'symbol'])


def downgrade() -> None:
    op.drop_index('ix_order_user_symbol', 'orders')
    op.drop_index('ix_order_user_status', 'orders')
    op.drop_index('ix_position_user_symbol_status', 'positions')
    op.drop_index('ix_position_user_status', 'positions')
