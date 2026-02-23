"""unify fee field names

Revision ID: u1n2i3f4y5f6
Create Date: 2026-02-23

Renames:
- positions.total_fee -> total_commission (not applicable, already named total_commission)
- grid_bots.total_fee -> total_commission  
- positions.accumulated_funding_fee -> total_funding_fee
"""
from alembic import op

revision = 'u1n2i3f4y5f6'
down_revision = None  # Will be auto-set by Alembic
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GridBot: total_fee -> total_commission (统一手续费字段名)
    op.alter_column('grid_bots', 'total_fee', new_column_name='total_commission')
    
    # Position: accumulated_funding_fee -> total_funding_fee (统一资金费率字段名)
    op.alter_column('positions', 'accumulated_funding_fee', new_column_name='total_funding_fee')


def downgrade() -> None:
    op.alter_column('grid_bots', 'total_commission', new_column_name='total_fee')
    op.alter_column('positions', 'total_funding_fee', new_column_name='accumulated_funding_fee')
