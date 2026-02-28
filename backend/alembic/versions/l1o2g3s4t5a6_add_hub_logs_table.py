"""add hub_logs table

Revision ID: l1o2g3s4t5a6
Revises: h1u2b3a4g5e6
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa


revision = 'l1o2g3s4t5a6'
down_revision = 'h1u2b3a4g5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'hub_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('agent_name', sa.String(100), nullable=False, server_default='System'),
        sa.Column('log_type', sa.String(20), nullable=False, server_default='system'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_hub_logs_user_time', 'hub_logs', ['user_id', 'created_at'])
    op.create_index('idx_hub_logs_agent', 'hub_logs', ['agent_id'])


def downgrade() -> None:
    op.drop_index('idx_hub_logs_agent')
    op.drop_index('idx_hub_logs_user_time')
    op.drop_table('hub_logs')
