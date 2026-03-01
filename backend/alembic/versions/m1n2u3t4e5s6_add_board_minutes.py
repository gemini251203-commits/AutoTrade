"""add board_minutes table

Revision ID: m1n2u3t4e5s6
Revises: l1o2g3s4t5a6
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'm1n2u3t4e5s6'
down_revision = 'l1o2g3s4t5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'board_minutes',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('key_lessons', sa.Text(), nullable=False, server_default=''),
        sa.Column('importance', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('trade_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pnl_total', sa.Float(), nullable=False, server_default='0'),
        sa.Column('agents_mentioned', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'date', name='uq_board_minutes_user_date'),
    )
    op.create_index('ix_board_minutes_user_date', 'board_minutes', ['user_id', 'date'])


def downgrade():
    op.drop_index('ix_board_minutes_user_date')
    op.drop_table('board_minutes')
