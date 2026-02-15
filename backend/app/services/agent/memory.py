"""
Agent Memory
==============
会话记忆管理

负责:
- 加载会话历史消息 (滑动窗口)
- 保存新消息到数据库
- 自动生成会话标题
"""

from typing import List, Optional, Dict, Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import ChatConversation, ChatMessage


# 上下文窗口大小 (最近 N 条消息)
CONTEXT_WINDOW = 20


async def load_history(
    db: AsyncSession,
    conversation_id: int,
    limit: int = CONTEXT_WINDOW,
) -> List[Dict[str, str]]:
    """
    加载会话的历史消息

    Args:
        db: 数据库会话
        conversation_id: 对话 ID
        limit: 最大条数

    Returns:
        消息列表 [{"role": "user", "content": "..."}]
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    messages = list(reversed(result.scalars().all()))

    return [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]


async def save_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tool_args: Optional[str] = None,
    tool_result: Optional[str] = None,
) -> ChatMessage:
    """
    保存消息到数据库

    Args:
        db: 数据库会话
        conversation_id: 对话 ID
        role: 消息角色 (system/user/assistant/tool)
        content: 消息内容
        tool_name: 工具名称 (可选)
        tool_args: 工具参数 JSON (可选)
        tool_result: 工具结果 JSON (可选)

    Returns:
        已保存的 ChatMessage 对象
    """
    msg = ChatMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
    )
    db.add(msg)
    await db.flush()
    return msg


async def auto_title(
    db: AsyncSession,
    conversation_id: int,
    first_message: str,
) -> None:
    """
    自动设置会话标题 (取用户第一条消息前 30 字)

    只在会话标题为 "New Chat" 时更新
    """
    result = await db.execute(
        select(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if conv and conv.title == "New Chat":
        conv.title = first_message[:30].strip()
        if len(first_message) > 30:
            conv.title += "..."
        await db.flush()
