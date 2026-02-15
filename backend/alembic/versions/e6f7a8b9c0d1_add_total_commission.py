"""
Add total_commission to positions
=================================
Alembic migration: 新增 total_commission 字段

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'positions',
        sa.Column(
            'total_commission',
            sa.Numeric(precision=20, scale=8),
            nullable=False,
            server_default='0',
            comment='累计手续费 (开仓+平仓, USDT)',
        ),
    )


def downgrade() -> None:
    op.drop_column('positions', 'total_commission')
