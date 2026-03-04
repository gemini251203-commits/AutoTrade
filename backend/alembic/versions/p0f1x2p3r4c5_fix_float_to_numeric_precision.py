"""fix float columns to numeric precision

Float -> Numeric(20,8) for all monetary/price/pnl fields.
Affected tables: trade_memories, strategy_logs, board_minutes, news_alerts, news_thinkings

Revision ID: p0f1x2p3r4c5
Revises: m1n2u3t4e5s6
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'p0f1x2p3r4c5'
down_revision = 'm1n2u3t4e5s6'
branch_labels = None
depends_on = None


def upgrade():
    """
    将所有金额/价格/盈亏字段从 Float 迁移到 Numeric(20,8)。

    PostgreSQL 的 ALTER COLUMN ... TYPE NUMERIC(20,8) USING column::numeric(20,8)
    是在线操作，对于小表不会长时间锁表。
    """

    # ==================== trade_memories ====================
    for col_name in [
        'entry_price', 'exit_price', 'pnl_usdt',
        'margin_used', 'commission', 'pnl_pct',
    ]:
        op.alter_column(
            'trade_memories',
            col_name,
            existing_type=sa.Float(),
            type_=sa.Numeric(precision=20, scale=8),
            existing_nullable=True,
            postgresql_using=f'{col_name}::numeric(20,8)',
        )

    # ==================== strategy_logs ====================
    op.alter_column(
        'strategy_logs',
        'pnl',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=20, scale=8),
        existing_nullable=True,
        postgresql_using='pnl::numeric(20,8)',
    )

    # ==================== board_minutes ====================
    op.alter_column(
        'board_minutes',
        'pnl_total',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=20, scale=8),
        existing_nullable=False,
        existing_server_default='0',
        postgresql_using='pnl_total::numeric(20,8)',
    )

    # ==================== news_alerts ====================
    op.alter_column(
        'news_alerts',
        'total_pnl',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=20, scale=8),
        existing_nullable=False,
        existing_server_default='0',
        postgresql_using='total_pnl::numeric(20,8)',
    )

    # ==================== news_thinkings ====================
    op.alter_column(
        'news_thinkings',
        'trade_pnl',
        existing_type=sa.Float(),
        type_=sa.Numeric(precision=20, scale=8),
        existing_nullable=True,
        postgresql_using='trade_pnl::numeric(20,8)',
    )


def downgrade():
    """
    回滚: Numeric(20,8) -> Float

    ⚠️ 注意: 回滚会丢失 Numeric 的精度优势，
    但数据本身不会丢失 (Float 精度足以表示常规金融数据)。
    """

    # ==================== news_thinkings ====================
    op.alter_column(
        'news_thinkings',
        'trade_pnl',
        existing_type=sa.Numeric(precision=20, scale=8),
        type_=sa.Float(),
        existing_nullable=True,
    )

    # ==================== news_alerts ====================
    op.alter_column(
        'news_alerts',
        'total_pnl',
        existing_type=sa.Numeric(precision=20, scale=8),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default='0',
    )

    # ==================== board_minutes ====================
    op.alter_column(
        'board_minutes',
        'pnl_total',
        existing_type=sa.Numeric(precision=20, scale=8),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default='0',
    )

    # ==================== strategy_logs ====================
    op.alter_column(
        'strategy_logs',
        'pnl',
        existing_type=sa.Numeric(precision=20, scale=8),
        type_=sa.Float(),
        existing_nullable=True,
    )

    # ==================== trade_memories ====================
    for col_name in [
        'entry_price', 'exit_price', 'pnl_usdt',
        'margin_used', 'commission', 'pnl_pct',
    ]:
        op.alter_column(
            'trade_memories',
            col_name,
            existing_type=sa.Numeric(precision=20, scale=8),
            type_=sa.Float(),
            existing_nullable=True,
        )
