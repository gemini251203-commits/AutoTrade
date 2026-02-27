"""add analysis_scratchpads table

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-02-27

AI 分析记事本 — 跨周期持久化 AI 中间分析状态
"""
from alembic import op
import sqlalchemy as sa


revision = 'n2o3p4q5r6s7'
down_revision = 'm1n2o3p4q5r6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'analysis_scratchpads',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户 ID'),
        sa.Column('symbol', sa.String(20), nullable=False, comment='交易对'),
        sa.Column('source', sa.String(50), nullable=False, server_default='autopilot',
                  comment='来源: autopilot / ai_reviewer'),
        sa.Column('context', sa.Text(), nullable=False, server_default='',
                  comment='AI 上次的分析结论'),
        sa.Column('key_levels', sa.JSON(), nullable=True,
                  comment='关键价位 {"support": [...], "resistance": [...]}'),
        sa.Column('pattern_tracking', sa.JSON(), nullable=True,
                  comment='形态追踪 {"type": "w_bottom", "stage": "..."}'),
        sa.Column('cycle_count', sa.Integer(), nullable=False, server_default='0',
                  comment='已更新次数'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'ix_scratchpad_user_symbol',
        'analysis_scratchpads',
        ['user_id', 'symbol', 'source'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table('analysis_scratchpads')
