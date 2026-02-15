"""add trade journal fields

Revision ID: d5e6f7a8b9c0
Revises: c8d9e0f1a2b3
Create Date: 2026-02-16 03:50:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c0'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ========================================
    # positions 表新增字段
    # ========================================
    op.add_column('positions', sa.Column('source', sa.String(20), nullable=True, server_default='manual', comment='交易来源: manual/agent/signal/quant'))
    op.add_column('positions', sa.Column('open_reason', sa.Text(), nullable=True, comment='开仓理由'))
    
    # 回填已有数据
    op.execute("UPDATE positions SET source = 'manual' WHERE source IS NULL")
    
    # 设为 NOT NULL
    op.alter_column('positions', 'source', nullable=False)
    
    # ========================================
    # trade_memories 表新增字段
    # ========================================
    op.add_column('trade_memories', sa.Column('source', sa.String(20), nullable=True, server_default='quant', comment='来源: manual/agent/signal/quant'))
    op.add_column('trade_memories', sa.Column('position_id', sa.Integer(), nullable=True, comment='关联仓位 ID'))
    op.add_column('trade_memories', sa.Column('side', sa.String(10), nullable=True, comment='方向: long/short'))
    op.add_column('trade_memories', sa.Column('entry_price', sa.Float(), nullable=True, comment='开仓价格'))
    op.add_column('trade_memories', sa.Column('exit_price', sa.Float(), nullable=True, comment='平仓价格'))
    op.add_column('trade_memories', sa.Column('leverage', sa.Integer(), nullable=True, comment='杠杆倍数'))
    op.add_column('trade_memories', sa.Column('margin_used', sa.Float(), nullable=True, comment='使用保证金'))
    op.add_column('trade_memories', sa.Column('pnl_usdt', sa.Float(), nullable=True, comment='盈亏金额'))
    op.add_column('trade_memories', sa.Column('duration_minutes', sa.Integer(), nullable=True, comment='持仓时长'))
    op.add_column('trade_memories', sa.Column('close_reason', sa.String(30), nullable=True, comment='平仓原因'))
    op.add_column('trade_memories', sa.Column('had_stop_loss', sa.Boolean(), nullable=True, comment='是否设了止损'))
    op.add_column('trade_memories', sa.Column('had_take_profit', sa.Boolean(), nullable=True, comment='是否设了止盈'))
    op.add_column('trade_memories', sa.Column('open_reason', sa.Text(), nullable=True, comment='开仓理由'))
    op.add_column('trade_memories', sa.Column('indicators_snapshot', sa.Text(), nullable=True, comment='指标快照'))
    
    # 回填已有记忆
    op.execute("UPDATE trade_memories SET source = 'quant' WHERE source IS NULL")
    
    # situation 和 lesson 改为 nullable
    op.alter_column('trade_memories', 'situation', nullable=True, existing_type=sa.Text())
    op.alter_column('trade_memories', 'lesson', nullable=True, existing_type=sa.Text())
    
    # 新增索引
    op.create_index('ix_trade_memories_source', 'trade_memories', ['user_id', 'source'])


def downgrade() -> None:
    # trade_memories 表
    op.drop_index('ix_trade_memories_source')
    op.drop_column('trade_memories', 'indicators_snapshot')
    op.drop_column('trade_memories', 'open_reason')
    op.drop_column('trade_memories', 'had_take_profit')
    op.drop_column('trade_memories', 'had_stop_loss')
    op.drop_column('trade_memories', 'close_reason')
    op.drop_column('trade_memories', 'duration_minutes')
    op.drop_column('trade_memories', 'pnl_usdt')
    op.drop_column('trade_memories', 'margin_used')
    op.drop_column('trade_memories', 'leverage')
    op.drop_column('trade_memories', 'exit_price')
    op.drop_column('trade_memories', 'entry_price')
    op.drop_column('trade_memories', 'side')
    op.drop_column('trade_memories', 'position_id')
    op.drop_column('trade_memories', 'source')
    
    # positions 表
    op.drop_column('positions', 'open_reason')
    op.drop_column('positions', 'source')
