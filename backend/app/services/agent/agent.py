"""
Agent Engine
==============
AI 交易代理核心引擎

流程:
1. 接收用户消息
2. 加载会话历史 (最近 20 条)
3. 注入实时上下文 (余额 + 持仓 + 价格)
4. 构建 system prompt (角色 + 工具 + 上下文)
5. 发送给 AI Provider (DeepSeek/Ollama)
6. 解析回复中的 [TOOL_CALL:...] 标记
7. 执行工具 → 结果反馈给 AI → 获取最终回复
8. 流式返回给前端
"""

import re
import json
from typing import AsyncGenerator, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.services.ai.brain import AIBrain
from app.services.ai.providers import ChatMessage as ProviderMessage
from .prompts import build_system_prompt
from .tools import TOOL_REGISTRY
from . import memory


# 工具调用正则: [TOOL_CALL: tool_name(param1=value1, param2=value2)]
TOOL_CALL_PATTERN = re.compile(
    r'\[TOOL_CALL:\s*(\w+)\(([^)]*)\)\]'
)


def _parse_tool_args(args_str: str) -> Dict[str, str]:
    """
    解析工具参数字符串

    输入: "symbol=BTCUSDT, side=buy, quantity=0.01"
    输出: {"symbol": "BTCUSDT", "side": "buy", "quantity": "0.01"}
    """
    if not args_str.strip():
        return {}

    params = {}
    for pair in args_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key.strip()] = value.strip()
    return params


def _cast_arg(value: str) -> Any:
    """尝试将字符串参数转为合适的类型"""
    # 整数
    if value.isdigit():
        return int(value)
    # 浮点数
    try:
        return float(value)
    except ValueError:
        pass
    return value


async def _build_context_text(db: AsyncSession, user_id: int) -> str:
    """构建实时上下文文本"""
    context = await AIBrain.build_context(db, user_id)
    return AIBrain._format_context(context)


async def execute_tool(
    tool_name: str,
    args: Dict[str, str],
    db: AsyncSession,
    user_id: int,
) -> str:
    """
    执行单个工具

    Args:
        tool_name: 工具名称 (如 get_price, place_order)
        args: 工具参数字典
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        工具执行结果 (JSON 字符串)
    """
    tool_fn = TOOL_REGISTRY.get(tool_name)
    if not tool_fn:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

    try:
        # 转换参数类型
        typed_args = {k: _cast_arg(v) for k, v in args.items()}
        result = await tool_fn(db=db, user_id=user_id, **typed_args)
        return result
    except Exception as e:
        logger.error(f"[Agent] Tool {tool_name} failed: {e}")
        return json.dumps({"error": f"工具 {tool_name} 执行失败: {str(e)}"}, ensure_ascii=False)


async def chat_stream(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    user_message: str,
    persona: str = "conservative",
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    处理用户消息并流式返回 AI 回复

    这是 Agent 的主入口. 使用 SSE 格式返回事件:
    - {"type": "text", "content": "..."}
    - {"type": "tool_call", "tool": "...", "args": {...}}
    - {"type": "tool_result", "tool": "...", "result": "..."}
    - {"type": "done", "full_reply": "..."}
    - {"type": "error", "message": "..."}

    Args:
        db: 数据库会话
        user_id: 用户 ID
        conversation_id: 对话 ID
        user_message: 用户消息
        persona: AI 角色

    Yields:
        SSE 事件字典
    """
    try:
        # 1. 保存用户消息
        await memory.save_message(db, conversation_id, "user", user_message)
        await memory.auto_title(db, conversation_id, user_message)

        # 2. 加载会话历史
        history = await memory.load_history(db, conversation_id)

        # 3. 构建上下文
        context_text = await _build_context_text(db, user_id)

        # 4. 构建 system prompt
        system_prompt = build_system_prompt(persona, context_text)

        # 5. 构建消息列表
        messages = [ProviderMessage(role="system", content=system_prompt)]
        for msg in history:
            messages.append(ProviderMessage(role=msg["role"], content=msg["content"]))

        # 6. 获取 AI Provider
        provider = await AIBrain.get_provider(db, user_id)

        # 7. 第一轮: 发送消息给 AI
        response = await provider.chat(
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
        )
        ai_content = response.content

        # 8. 检查是否包含工具调用
        tool_match = TOOL_CALL_PATTERN.search(ai_content)

        if tool_match:
            tool_name = tool_match.group(1)
            tool_args_str = tool_match.group(2)
            tool_args = _parse_tool_args(tool_args_str)

            # 发送工具调用事件
            yield {"type": "tool_call", "tool": tool_name, "args": tool_args}

            # 执行工具
            tool_result = await execute_tool(tool_name, tool_args, db, user_id)

            # 发送工具结果事件
            yield {"type": "tool_result", "tool": tool_name, "result": tool_result}

            # 保存工具调用记录
            await memory.save_message(
                db, conversation_id, "assistant", ai_content,
                tool_name=tool_name,
                tool_args=json.dumps(tool_args, ensure_ascii=False),
                tool_result=tool_result,
            )

            # 9. 第二轮: 将工具结果反馈给 AI
            messages.append(ProviderMessage(role="assistant", content=ai_content))
            messages.append(ProviderMessage(
                role="user",
                content=f"[TOOL_RESULT: {tool_name}]\n{tool_result}\n[/TOOL_RESULT]\n\n请根据工具返回的结果，用自然语言回复用户。不要再调用工具。"
            ))

            response2 = await provider.chat(
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
            final_content = response2.content

            # 清理可能残留的工具标记
            final_content = TOOL_CALL_PATTERN.sub("", final_content).strip()
        else:
            final_content = ai_content

        # 10. 流式输出最终回复 (模拟打字机效果)
        chunk_size = 3  # 每次发送 3 个字符
        for i in range(0, len(final_content), chunk_size):
            chunk = final_content[i:i + chunk_size]
            yield {"type": "text", "content": chunk}

        # 11. 保存 AI 最终回复
        await memory.save_message(db, conversation_id, "assistant", final_content)
        await db.commit()

        # 12. 完成
        yield {"type": "done", "full_reply": final_content}

    except Exception as e:
        logger.error(f"[Agent] chat_stream error: {e}")
        await db.rollback()
        yield {"type": "error", "message": f"AI 处理出错: {str(e)}"}
