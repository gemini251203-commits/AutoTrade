"""
Alembic Migration: Strategy total_pnl Float → Numeric
======================================================
将 strategies 表的 total_pnl 列从 Float 改为 Numeric(20,8)
以避免浮点精度损失。

Revision ID: m1n2o3p4q5r6
Revises: k5l6m7n8o9p0
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'm1n2o3p4q5r6'
down_revision = 'l6m7n8o9p0q1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Float → Numeric(20, 8), 保留现有数据
    with op.batch_alter_table('strategies') as batch_op:
        batch_op.alter_column(
            'total_pnl',
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=20, scale=8),
            existing_nullable=False,
            existing_server_default=sa.text('0'),
        )


def downgrade() -> None:
    with op.batch_alter_table('strategies') as batch_op:
        batch_op.alter_column(
            'total_pnl',
            existing_type=sa.Numeric(precision=20, scale=8),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default=sa.text('0'),
        )
