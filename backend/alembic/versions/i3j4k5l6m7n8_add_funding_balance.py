"""
Add funding_balance to wallets table
"""

from alembic import op
import sqlalchemy as sa

revision = 'i3j4k5l6m7n8'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('wallets', sa.Column(
        'funding_balance',
        sa.Numeric(precision=20, scale=8),
        nullable=False,
        server_default='0',
    ))
    # Add check constraint
    op.create_check_constraint(
        'check_funding_non_negative',
        'wallets',
        'funding_balance >= 0',
    )


def downgrade() -> None:
    op.drop_constraint('check_funding_non_negative', 'wallets', type_='check')
    op.drop_column('wallets', 'funding_balance')
