"""
Agent Memory
==============
会话记忆管理

负责:
- 加载会话历史消息 (Token 级滑动窗口)
- 保存新消息到数据库
- 自动生成会话标题
- 历史消息摘要压缩
"""

from typing import List, Optional, Dict, Any

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.agent import ChatConversation, ChatMessage


# ==================== Token 级截断 ====================
# 使用 字符数 / 4 估算 token 数 (中英文混合场景的保守估算)
MAX_HISTORY_TOKENS = 8000

# 摘要压缩触发阈值: 每积累 N 条消息, 自动压缩老消息
SUMMARIZE_THRESHOLD = 10
# 摘要最大字符数
SUMMARY_MAX_CHARS = 400


def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数 (字符数 / 4, 适用于中英文混合)"""
    if not text:
        return 0
    return len(text) // 4


async def load_history(
    db: AsyncSession,
    conversation_id: int,
) -> List[Dict[str, str]]:
    """
    加载会话的历史消息 (Token 级截断)

    从最新消息开始倒推, 一旦累计达到 MAX_HISTORY_TOKENS 立刻截断。
    如果存在上下文摘要 (role=system, content 以 [Context Summary] 开头),
    将其置于历史消息最前面。

    Returns:
        消息列表 [{"role": "user", "content": "..."}]
    """
    # 拉取最近 50 条 (足够大的上限, 由 token 计数实际控制截断)
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(desc(ChatMessage.created_at))
        .limit(50)
    )
    all_messages = list(result.scalars().all())

    # 从最新往回倒推, 按 token 截断
    selected = []
    token_budget = MAX_HISTORY_TOKENS
    context_summary = None

    for msg in all_messages:
        # 检查是否是上下文摘要 (由摘要压缩机制生成)
        if msg.role == "system" and msg.content and msg.content.startswith("[Context Summary]"):
            context_summary = msg
            continue

        msg_tokens = _estimate_tokens(msg.content or "")

        if token_budget - msg_tokens < 0:
            # 预算用尽, 截断
            logger.debug(
                f"[Memory] Token truncation: kept {len(selected)} msgs, "
                f"budget exhausted at msg #{msg.id} ({msg_tokens} tokens)"
            )
            break

        token_budget -= msg_tokens
        selected.append(msg)

    # 反转回时间顺序 (旧->新)
    selected.reverse()

    # 构建结果: 摘要在最前面
    history = []
    if context_summary:
        history.append({"role": "system", "content": context_summary.content})

    for msg in selected:
        history.append({"role": msg.role, "content": msg.content})

    total_tokens = MAX_HISTORY_TOKENS - token_budget
    logger.info(
        f"[Memory] Loaded {len(history)} msgs (~{total_tokens} tokens) "
        f"for conversation {conversation_id}"
    )

    return history


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


# ==================== 历史摘要压缩 ====================

async def maybe_summarize_history(
    db: AsyncSession,
    conversation_id: int,
) -> None:
    """
    检查是否需要压缩历史消息

    每积累 SUMMARIZE_THRESHOLD 条消息, 将最老的消息
    压缩为一段 ~100 字的上下文摘要, 以 [Context Summary] 开头
    保存为 system 消息。

    注意: 使用简单规则提取摘要 (非 AI), 避免额外 API 开销。
    """
    # 统计消息数
    count_result = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role != "system",  # 不计算 system 消息
        )
    )
    total_count = count_result.scalar() or 0

    if total_count < SUMMARIZE_THRESHOLD:
        return

    # 检查是否已有摘要 (避免重复)
    existing = await db.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "system",
            ChatMessage.content.like("[Context Summary]%"),
        ).limit(1)
    )
    existing_summary = existing.scalar_one_or_none()

    # 只在消息数超过阈值的整数倍时触发
    if existing_summary and total_count < SUMMARIZE_THRESHOLD * 2:
        return

    # 取最老的 SUMMARIZE_THRESHOLD 条消息
    old_result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role != "system",
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(SUMMARIZE_THRESHOLD)
    )
    old_messages = old_result.scalars().all()

    if not old_messages:
        return

    # 规则摘要 (非 AI, 零开销): 提取关键信息
    summary_parts = []
    for msg in old_messages:
        content = msg.content or ""
        # 提取首行作为关键信息
        first_line = content.split("\n")[0][:80]
        if msg.role == "user":
            summary_parts.append(f"User: {first_line}")
        elif msg.role == "assistant" and not content.startswith("["):
            summary_parts.append(f"AI: {first_line}")

    summary_text = (
        f"[Context Summary] 以下是之前对话的摘要 (共{len(old_messages)}条):\n"
        + "\n".join(summary_parts[:5])  # 最多 5 条摘要行
    )

    # 截断到最大长度
    if len(summary_text) > SUMMARY_MAX_CHARS:
        summary_text = summary_text[:SUMMARY_MAX_CHARS] + "..."

    # 更新或创建摘要
    if existing_summary:
        existing_summary.content = summary_text
    else:
        summary_msg = ChatMessage(
            conversation_id=conversation_id,
            role="system",
            content=summary_text,
        )
        db.add(summary_msg)

    await db.flush()
    logger.info(
        f"[Memory] Summarized {len(old_messages)} old messages "
        f"for conversation {conversation_id}"
    )
