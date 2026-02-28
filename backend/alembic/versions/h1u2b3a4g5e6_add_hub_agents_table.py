"""
Add hub_agents table

Revision ID: h1u2b3a4g5e6
Revises: n2o3p4q5r6s7
Create Date: 2026-02-28

Tables:
- hub_agents: Agent Hub 智能体配置与状态
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'h1u2b3a4g5e6'
down_revision = 'n2o3p4q5r6s7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'hub_agents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('role', sa.String(50), server_default='trader', nullable=False),
        sa.Column('avatar', sa.String(20), server_default='🤖', nullable=False),
        sa.Column('provider', sa.String(20), server_default='deepseek', nullable=False),
        sa.Column('model', sa.String(100), server_default='deepseek-chat', nullable=False),
        sa.Column('api_base_url', sa.String(255), nullable=True),
        sa.Column('api_key_enc', sa.Text(), nullable=True),
        sa.Column('system_prompt', sa.Text(), server_default='', nullable=False),
        sa.Column('temperature', sa.Float(), server_default='0.7', nullable=False),
        sa.Column('status', sa.Enum('idle', 'active', 'paused', 'error', name='hub_agent_status'), server_default='idle', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('total_runs', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_trades', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_hub_agents_user_active',
        'hub_agents',
        ['user_id', 'is_active'],
    )


def downgrade() -> None:
    op.drop_index('ix_hub_agents_user_active', table_name='hub_agents')
    op.drop_table('hub_agents')
    op.execute("DROP TYPE IF EXISTS hub_agent_status")
