"""
Add chat agent tables

Revision ID: c8d9e0f1a2b3
Revises: a1b2c3d4e5f6
Create Date: 2026-02-15

Tables:
- chat_conversations: AI 对话会话
- chat_messages: 对话消息
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'c8d9e0f1a2b3'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chat_conversations 表
    op.create_table(
        'chat_conversations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(100), server_default='New Chat', nullable=False),
        sa.Column('persona', sa.String(20), server_default='conservative', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_chat_conversations_user',
        'chat_conversations',
        ['user_id', 'updated_at'],
    )

    # chat_messages 表
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_name', sa.String(50), nullable=True),
        sa.Column('tool_args', sa.Text(), nullable=True),
        sa.Column('tool_result', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['chat_conversations.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_chat_messages_conv',
        'chat_messages',
        ['conversation_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_chat_messages_conv', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index('ix_chat_conversations_user', table_name='chat_conversations')
    op.drop_table('chat_conversations')
