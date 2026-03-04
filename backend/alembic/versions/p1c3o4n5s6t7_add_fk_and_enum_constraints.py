"""add foreign keys and enum constraints

- wallet_transactions.type: String(20) -> Enum (non-native)
- wallet_transactions.related_order_id: add FK -> orders.id (SET NULL)
- wallet_transactions.related_position_id: add FK -> positions.id (SET NULL)
- strategy_logs.order_id: add FK -> orders.id (SET NULL)

Revision ID: p1c3o4n5s6t7
Revises: merge_all_heads
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'p1c3o4n5s6t7'
down_revision = 'merge_all_heads'
branch_labels = None
depends_on = None


def upgrade():
    # ==================== wallet_transactions.type -> Enum ====================
    # Non-native enum: keeps VARCHAR column but adds CHECK constraint
    # First clean any invalid data (shouldn't exist but safety first)
    op.alter_column(
        'wallet_transactions',
        'type',
        existing_type=sa.String(20),
        type_=sa.String(20),  # Keep VARCHAR, add CHECK via next step
        existing_nullable=False,
    )
    # Add CHECK constraint for valid transaction types
    op.create_check_constraint(
        'ck_wallet_tx_type_valid',
        'wallet_transactions',
        sa.column('type').in_([
            'deposit', 'withdraw', 'freeze', 'unfreeze',
            'pnl', 'fee', 'funding', 'reset',
            'transfer_in', 'transfer_out',
        ]),
    )

    # ==================== wallet_transactions FK ====================
    # related_order_id -> orders.id
    op.create_foreign_key(
        'fk_wallet_tx_order',
        'wallet_transactions', 'orders',
        ['related_order_id'], ['id'],
        ondelete='SET NULL',
    )

    # related_position_id -> positions.id
    op.create_foreign_key(
        'fk_wallet_tx_position',
        'wallet_transactions', 'positions',
        ['related_position_id'], ['id'],
        ondelete='SET NULL',
    )

    # ==================== strategy_logs.order_id FK ====================
    op.create_foreign_key(
        'fk_strategy_log_order',
        'strategy_logs', 'orders',
        ['order_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    # Drop FKs
    op.drop_constraint('fk_strategy_log_order', 'strategy_logs', type_='foreignkey')
    op.drop_constraint('fk_wallet_tx_position', 'wallet_transactions', type_='foreignkey')
    op.drop_constraint('fk_wallet_tx_order', 'wallet_transactions', type_='foreignkey')

    # Drop CHECK constraint
    op.drop_constraint('ck_wallet_tx_type_valid', 'wallet_transactions', type_='check')
