"""
Add prompt_templates and prompt_activation_logs tables

Revision ID: p1r2o3m4p5t6
Revises: v1w2x3y4z5a6
Create Date: 2026-04-01

Tables:
- prompt_templates: 提示词模板版本管理
- prompt_activation_logs: 模板激活日志
- hub_agents.active_template_id: 关联字段
- positions.prompt_template_id: 收益追踪字段
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'p1r2o3m4p5t6'
down_revision = 'v1w2x3y4z5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 创建 prompt_templates 表
    op.create_table(
        'prompt_templates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('strategy_prompt', sa.Text(), server_default='', nullable=False),
        sa.Column('risk_rules', sa.Text(), server_default='', nullable=False),
        sa.Column('behavior_directives', sa.Text(), server_default='', nullable=False),
        sa.Column('raw_prompt', sa.Text(), server_default='', nullable=False),
        sa.Column('is_structured', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('market_tags', sa.JSON(), nullable=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('is_preset', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('total_trades', sa.Integer(), server_default='0', nullable=False),
        sa.Column('win_trades', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_pnl', sa.Numeric(20, 8), server_default='0', nullable=False),
        sa.Column('active_hours', sa.Float(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['prompt_templates.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_prompt_templates_user', 'prompt_templates', ['user_id'])
    op.create_index('ix_prompt_templates_user_name', 'prompt_templates', ['user_id', 'name'])

    # 2. 创建 prompt_activation_logs 表
    op.create_table(
        'prompt_activation_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('activated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('deactivated_at', sa.DateTime(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['hub_agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['prompt_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_prompt_activation_user_agent', 'prompt_activation_logs', ['user_id', 'agent_id'])
    op.create_index('ix_prompt_activation_template', 'prompt_activation_logs', ['template_id'])

    # 3. 为 hub_agents 添加 active_template_id 字段
    op.add_column('hub_agents', sa.Column(
        'active_template_id', sa.Integer(), nullable=True,
    ))
    op.create_foreign_key(
        'fk_hub_agents_active_template',
        'hub_agents', 'prompt_templates',
        ['active_template_id'], ['id'],
        ondelete='SET NULL',
    )

    # 4. 为 positions 添加 prompt_template_id 字段
    op.add_column('positions', sa.Column(
        'prompt_template_id', sa.Integer(), nullable=True,
    ))


def downgrade() -> None:
    # 4. 移除 positions.prompt_template_id
    op.drop_column('positions', 'prompt_template_id')

    # 3. 移除 hub_agents.active_template_id
    op.drop_constraint('fk_hub_agents_active_template', 'hub_agents', type_='foreignkey')
    op.drop_column('hub_agents', 'active_template_id')

    # 2. 删除 prompt_activation_logs 表
    op.drop_index('ix_prompt_activation_template', table_name='prompt_activation_logs')
    op.drop_index('ix_prompt_activation_user_agent', table_name='prompt_activation_logs')
    op.drop_table('prompt_activation_logs')

    # 1. 删除 prompt_templates 表
    op.drop_index('ix_prompt_templates_user_name', table_name='prompt_templates')
    op.drop_index('ix_prompt_templates_user', table_name='prompt_templates')
    op.drop_table('prompt_templates')
