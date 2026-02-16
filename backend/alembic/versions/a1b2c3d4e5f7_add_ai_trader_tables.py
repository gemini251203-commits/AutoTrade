"""add ai_trader tables

Revision ID: a1b2c3d4e5f7
Revises: d5e6f7a8b9c0
Create Date: 2026-02-16 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AI Trader 决策记录表
    op.create_table(
        'ai_trader_decisions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False),
        sa.Column('cycle_no', sa.Integer(), default=0),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('reasoning', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), default=0.0),
        sa.Column('market_snapshot', sa.JSON(), nullable=True),
        sa.Column('account_snapshot', sa.JSON(), nullable=True),
        sa.Column('experience_used', sa.JSON(), nullable=True),
        sa.Column('risk_params', sa.JSON(), nullable=True),
        sa.Column('executed', sa.Boolean(), default=False),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('reject_reason', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_trader_decisions_user_time', 'ai_trader_decisions', ['user_id', 'created_at'])
    op.create_index('ix_ai_trader_decisions_user_symbol', 'ai_trader_decisions', ['user_id', 'symbol'])

    # AI Trader 配置表
    op.create_table(
        'ai_trader_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=False),
        sa.Column('symbols', sa.JSON(), nullable=True),
        sa.Column('interval', sa.String(10), default='15m'),
        sa.Column('max_position_pct', sa.Float(), default=30.0),
        sa.Column('max_leverage', sa.Integer(), default=20),
        sa.Column('min_confidence', sa.Float(), default=0.6),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_ai_trader_configs_user', 'ai_trader_configs', ['user_id'])


def downgrade() -> None:
    op.drop_table('ai_trader_configs')
    op.drop_table('ai_trader_decisions')
