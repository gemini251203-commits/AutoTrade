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
            value = value.strip()
            # AI 经常在值两端加引号, 去掉它们
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            params[key.strip()] = value
    return params


# 需要从正文中提取 YAML 的工具列表
_YAML_BODY_TOOLS = frozenset({"create_strategy", "update_strategy", "create_pipeline_strategy"})


def _extract_yaml_arg(
    tool_name: str,
    ai_content: str,
    tool_args: Dict[str, str],
) -> Dict[str, str]:
    """
    若工具需要 YAML 参数，从 AI 回复正文的 ```yaml 代码块中提取。

    背景: TOOL_CALL_PATTERN 用 [^)]* 匹配参数，无法处理多行 YAML。
    因此约定 AI 将 YAML 写在正文代码块中，而非 TOOL_CALL 参数里。
    """
    if tool_name in _YAML_BODY_TOOLS and "config_yaml" not in tool_args:
        yaml_match = re.search(r"```yaml\s*\n(.*?)\n```", ai_content, re.DOTALL)
        if yaml_match:
            tool_args["config_yaml"] = yaml_match.group(1).strip()
    return tool_args


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
    """
    tool_fn = TOOL_REGISTRY.get(tool_name)
    if not tool_fn:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)

    try:
        # 转换参数类型
        typed_args = {k: _cast_arg(v) for k, v in args.items()}
        logger.info(f"[Agent] Calling tool: {tool_name}({typed_args})")
        result = await tool_fn(db=db, user_id=user_id, **typed_args)
        logger.info(f"[Agent] Tool {tool_name} returned: {result[:200]}")
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

    支持多轮工具调用 (最多 5 轮):
    AI 可以连续调用多个工具完成复杂任务，如:
    get_balance() → get_price() → place_order() → 失败后自动调整参数重试

    Yields:
        SSE 事件字典
    """
    MAX_TOOL_ROUNDS = 5

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

        # 7. 多轮工具调用循环
        final_content = ""
        tool_calls_log = []  # 记录所有工具调用

        for round_i in range(MAX_TOOL_ROUNDS + 1):
            response = await provider.chat(
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
            ai_content = response.content

            # 查找所有工具调用
            tool_matches = TOOL_CALL_PATTERN.findall(ai_content)

            if not tool_matches:
                # 没有工具调用 → 这就是最终回复
                final_content = ai_content
                break

            if round_i >= MAX_TOOL_ROUNDS:
                # 超过最大轮次，强制结束
                final_content = TOOL_CALL_PATTERN.sub("", ai_content).strip()
                if not final_content:
                    final_content = "已达到最大操作轮次，请查看上方的工具执行结果。"
                break

            # 执行所有工具调用
            results_text_parts = []
            for tool_name, args_str in tool_matches:
                tool_args = _parse_tool_args(args_str)
                tool_args = _extract_yaml_arg(tool_name, ai_content, tool_args)

                # 发送工具调用事件
                yield {"type": "tool_call", "tool": tool_name, "args": tool_args}

                # 执行工具
                tool_result = await execute_tool(tool_name, tool_args, db, user_id)

                # 发送工具结果事件
                yield {"type": "tool_result", "tool": tool_name, "result": tool_result}

                results_text_parts.append(
                    f"[TOOL_RESULT: {tool_name}]\n{tool_result}\n[/TOOL_RESULT]"
                )
                tool_calls_log.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                })

            # 将工具结果反馈给 AI，进入下一轮
            messages.append(ProviderMessage(role="assistant", content=ai_content))
            all_results = "\n\n".join(results_text_parts)
            messages.append(ProviderMessage(
                role="user",
                content=(
                    f"{all_results}\n\n"
                    f"请根据以上工具结果继续回答用户的原始问题。"
                    f"如果用户明确要求了交易操作且你还需要调用工具，使用 [TOOL_CALL: ...] 继续。"
                    f"如果信息已足够，直接用自然语言回答用户的问题。"
                ),
            ))

        # 保存工具调用记录 (第一次工具调用)
        if tool_calls_log:
            first = tool_calls_log[0]
            await memory.save_message(
                db, conversation_id, "assistant",
                f"[执行了 {len(tool_calls_log)} 个操作]",
                tool_name=first["tool"],
                tool_args=json.dumps(first["args"], ensure_ascii=False),
                tool_result=first["result"],
            )

        # 8. 流式输出最终回复
        # 如果最终回复已经有了(工具调用循环中), 判断是否需要再次流式请求
        if final_content:
            # 清理可能残留的工具标记
            final_content = TOOL_CALL_PATTERN.sub("", final_content).strip()
            # 已有内容，真流式逐段发送
            chunk_size = 10
            for i in range(0, len(final_content), chunk_size):
                chunk = final_content[i:i + chunk_size]
                yield {"type": "text", "content": chunk}
        else:
            # 没有最终内容 (不太可能到这里)
            final_content = "（无回复）"
            yield {"type": "text", "content": final_content}

        # 9. 保存 AI 最终回复
        await memory.save_message(db, conversation_id, "assistant", final_content)
        await db.commit()

        # 10. 完成
        yield {"type": "done", "full_reply": final_content}

    except Exception as e:
        logger.error(f"[Agent] chat_stream error: {e}")
        await db.rollback()
        yield {"type": "error", "message": f"AI 处理出错: {str(e)}"}


async def chat_complete(
    db: AsyncSession,
    user_id: int,
    conversation_id: int,
    user_message: str,
    persona: str = "conservative",
) -> str:
    """
    非流式版本 — 供 autopilot 内部调用

    与 chat_stream 逻辑相同 (多轮工具调用), 但直接返回最终回复文本。

    Returns:
        AI 最终回复文本
    """
    MAX_TOOL_ROUNDS = 5

    try:
        # 1. 保存用户消息
        await memory.save_message(db, conversation_id, "user", user_message)

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

        # 7. 多轮工具调用循环
        final_content = ""
        tool_calls_log = []

        for round_i in range(MAX_TOOL_ROUNDS + 1):
            response = await provider.chat(
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
            ai_content = response.content

            tool_matches = TOOL_CALL_PATTERN.findall(ai_content)

            if not tool_matches:
                final_content = ai_content
                break

            if round_i >= MAX_TOOL_ROUNDS:
                final_content = TOOL_CALL_PATTERN.sub("", ai_content).strip()
                if not final_content:
                    final_content = "已达到最大操作轮次。"
                break

            results_text_parts = []
            for tool_name, args_str in tool_matches:
                tool_args = _parse_tool_args(args_str)
                tool_args = _extract_yaml_arg(tool_name, ai_content, tool_args)

                tool_result = await execute_tool(tool_name, tool_args, db, user_id)
                results_text_parts.append(
                    f"[TOOL_RESULT: {tool_name}]\n{tool_result}\n[/TOOL_RESULT]"
                )
                tool_calls_log.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": tool_result,
                })

            messages.append(ProviderMessage(role="assistant", content=ai_content))
            all_results = "\n\n".join(results_text_parts)
            messages.append(ProviderMessage(
                role="user",
                content=(
                    f"{all_results}\n\n"
                    f"请根据以上工具结果继续。"
                    f"如果需要额外操作, 继续使用 [TOOL_CALL: ...] 调用工具。"
                    f"如果所有操作已完成, 直接用自然语言总结结果。"
                ),
            ))

        # 清理残留工具标记
        final_content = TOOL_CALL_PATTERN.sub("", final_content).strip()

        # 保存工具调用记录
        if tool_calls_log:
            first = tool_calls_log[0]
            await memory.save_message(
                db, conversation_id, "assistant",
                f"[执行了 {len(tool_calls_log)} 个操作]",
                tool_name=first["tool"],
                tool_args=json.dumps(first["args"], ensure_ascii=False),
                tool_result=first["result"],
            )

        # 保存 AI 最终回复
        await memory.save_message(db, conversation_id, "assistant", final_content)

        return final_content

    except Exception as e:
        logger.error(f"[Agent] chat_complete error: {e}")
        raise
