"""
Add autopilot_logs table

Revision ID: g1h2i3j4k5l6
Revises: e6f7a8b9c0d1
Create Date: 2026-02-16

Tables:
- autopilot_logs: Autopilot 决策日志 (思考过程 + 决策 + 操作)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'g1h2i3j4k5l6'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'autopilot_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('decision', sa.String(20), server_default='hold', nullable=False),
        sa.Column('thinking', sa.Text(), server_default='', nullable=False),
        sa.Column('summary', sa.String(200), server_default='', nullable=False),
        sa.Column('market_snapshot', sa.JSON(), nullable=True),
        sa.Column('action_taken', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_autopilot_logs_user_time',
        'autopilot_logs',
        ['user_id', 'created_at'],
    )
    op.create_index(
        'ix_autopilot_logs_user_symbol',
        'autopilot_logs',
        ['user_id', 'symbol'],
    )


def downgrade() -> None:
    op.drop_index('ix_autopilot_logs_user_symbol', table_name='autopilot_logs')
    op.drop_index('ix_autopilot_logs_user_time', table_name='autopilot_logs')
    op.drop_table('autopilot_logs')
