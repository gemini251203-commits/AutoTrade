"""add frozen_amount to orders

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-02-22 01:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column(
        'frozen_amount',
        sa.Numeric(precision=20, scale=8),
        nullable=False,
        server_default='0',
        comment='该订单冻结的保证金+手续费总额 (用于精确解冻)',
    ))


def downgrade() -> None:
    op.drop_column('orders', 'frozen_amount')
