"""add strategy tables

Revision ID: b7a9c3e1f502
Revises: f4dd271299aa
Create Date: 2026-02-15 19:14:00.000000

新增三张表:
- strategies: 策略配置 (YAML + 运行状态)
- strategy_logs: 策略执行日志
- trade_memories: AI 交易反思记忆库
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7a9c3e1f502'
down_revision: Union[str, Sequence[str], None] = 'f4dd271299aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === strategies ===
    op.create_table(
        'strategies',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False, comment='策略名称'),
        sa.Column('symbol', sa.String(20), nullable=False, comment='交易对'),
        sa.Column('interval', sa.String(10), nullable=False, server_default='1h', comment='K线周期'),
        sa.Column('config_yaml', sa.Text(), nullable=False, comment='YAML 策略配置'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false', comment='是否自动运行'),
        sa.Column('last_run_at', sa.DateTime(), nullable=True, comment='上次执行时间'),
        sa.Column('last_signal', sa.String(20), nullable=True, comment='上次信号类型'),
        sa.Column('total_trades', sa.Integer(), nullable=False, server_default='0', comment='总交易次数'),
        sa.Column('win_trades', sa.Integer(), nullable=False, server_default='0', comment='盈利次数'),
        sa.Column('total_pnl', sa.Float(), nullable=False, server_default='0', comment='累计盈亏'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_strategies_user_id', 'strategies', ['user_id'])
    op.create_index('ix_strategies_symbol', 'strategies', ['symbol'])
    op.create_index('ix_strategies_user_active', 'strategies', ['user_id', 'is_active'])

    # === strategy_logs ===
    op.create_table(
        'strategy_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('strategy_id', sa.Integer(), sa.ForeignKey('strategies.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('signal_type', sa.String(20), nullable=False, comment='信号类型'),
        sa.Column('action', sa.String(20), nullable=False, comment='实际动作'),
        sa.Column('side', sa.String(10), nullable=True, comment='方向'),
        sa.Column('ai_approve', sa.Boolean(), nullable=True, comment='AI 是否批准'),
        sa.Column('ai_confidence', sa.Float(), nullable=True, comment='AI 置信度'),
        sa.Column('ai_reason', sa.Text(), nullable=True, comment='AI 审核理由'),
        sa.Column('risk_passed', sa.Boolean(), nullable=True, comment='风控是否通过'),
        sa.Column('risk_reason', sa.Text(), nullable=True, comment='风控拦截原因'),
        sa.Column('order_id', sa.Integer(), nullable=True, comment='关联订单 ID'),
        sa.Column('pnl', sa.Float(), nullable=True, comment='盈亏'),
        sa.Column('conditions_snapshot', sa.Text(), nullable=True, comment='条件评估快照 JSON'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_strategy_logs_strategy_id', 'strategy_logs', ['strategy_id'])
    op.create_index('ix_strategy_logs_user_id', 'strategy_logs', ['user_id'])
    op.create_index('ix_strategy_logs_created', 'strategy_logs', ['strategy_id', 'created_at'])

    # === trade_memories ===
    op.create_table(
        'trade_memories',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('symbol', sa.String(20), nullable=False, comment='交易对'),
        sa.Column('strategy_name', sa.String(100), nullable=True, comment='策略名称'),
        sa.Column('trade_result', sa.String(10), nullable=False, comment='win/loss'),
        sa.Column('pnl_pct', sa.Float(), nullable=False, comment='盈亏百分比'),
        sa.Column('situation', sa.Text(), nullable=False, comment='市场环境摘要'),
        sa.Column('lesson', sa.Text(), nullable=False, comment='经验教训'),
        sa.Column('what_went_right', sa.Text(), nullable=True),
        sa.Column('what_went_wrong', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_trade_memories_user_id', 'trade_memories', ['user_id'])
    op.create_index('ix_trade_memories_symbol', 'trade_memories', ['user_id', 'symbol'])


def downgrade() -> None:
    op.drop_table('strategy_logs')
    op.drop_table('trade_memories')
    op.drop_table('strategies')
