"""add allowed_tools to hub_agents

Revision ID: t1o2l3s4p5e6
Revises: p1c3o4n5s6t7
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 't1o2l3s4p5e6'
down_revision = 'p1c3o4n5s6t7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'hub_agents',
        sa.Column(
            'allowed_tools',
            sa.JSON(),
            nullable=True,
            comment='授权工具列表 (JSON数组). null=全部, []=禁用',
        )
    )


def downgrade() -> None:
    op.drop_column('hub_agents', 'allowed_tools')
