"""add funding fee fields to positions and grid_bots

Revision ID: f1u2n3d4i5n6
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1u2n3d4i5n6'
down_revision = None  # Will be auto-set by Alembic
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Position: 累计资金费率费用
    op.add_column(
        'positions',
        sa.Column(
            'accumulated_funding_fee',
            sa.Numeric(precision=20, scale=8),
            nullable=False,
            server_default='0',
            comment='累计资金费率费用 (正=支出, 负=收入)',
        )
    )

    # GridBot: 累计资金费率费用
    op.add_column(
        'grid_bots',
        sa.Column(
            'total_funding_fee',
            sa.Numeric(precision=20, scale=8),
            nullable=False,
            server_default='0',
            comment='累计资金费率费用',
        )
    )


def downgrade() -> None:
    op.drop_column('grid_bots', 'total_funding_fee')
    op.drop_column('positions', 'accumulated_funding_fee')
