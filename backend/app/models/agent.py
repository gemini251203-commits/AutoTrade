"""
Agent Models
=============
AI 交易代理的数据模型

表:
- chat_conversations: 对话会话
- chat_messages: 对话消息
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String, Integer, Text, DateTime,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class ChatConversation(Base):
    """
    对话会话

    每个用户可以有多个独立会话，每个会话有独立的记忆
    """
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(100),
        default="New Chat",
        comment="会话标题 (取用户第一条消息前30字)",
    )
    persona: Mapped[str] = mapped_column(
        String(20),
        default="conservative",
        comment="AI 角色: conservative/aggressive/quant/mentor",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        Index("ix_chat_conversations_user", "user_id", "updated_at"),
    )

    def __repr__(self):
        return f"<ChatConversation {self.id} '{self.title}'>"


class ChatMessage(Base):
    """
    对话消息

    role:
    - system: 系统提示词
    - user: 用户消息
    - assistant: AI 回复
    - tool: 工具调用结果
    """
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(20),
        comment="消息角色: system/user/assistant/tool",
    )
    content: Mapped[str] = mapped_column(
        Text,
        comment="消息内容",
    )

    # 工具调用记录 (仅 role=assistant 时可能存在)
    tool_name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="调用的工具名称",
    )
    tool_args: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="工具参数 (JSON)",
    )
    tool_result: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="工具执行结果 (JSON)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    __table_args__ = (
        Index("ix_chat_messages_conv", "conversation_id", "created_at"),
    )

    def __repr__(self):
        return f"<ChatMessage {self.role}: {self.content[:30]}>"
