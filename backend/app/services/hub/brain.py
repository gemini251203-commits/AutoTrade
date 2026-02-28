"""
Hub Brain — 智能体 AI 调用封装
==================================
封装 AI 大模型调用，支持 SSE 流式对话 + 工具调用。

职责:
- 组装 messages (system_prompt + 用户消息)
- 调用 AI 大模型 (复用 UserAIConfig 或智能体独立配置)
- 解析 tool_call → 执行 tools.py → 返回结果
- SSE 流式输出

与现有 agent.py 的关系:
- 完全独立，不修改 agent.py
- 复用 tools.py 的 TOOL_REGISTRY (共享武器库)
"""

import json
import asyncio
from typing import AsyncGenerator, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hub_agent import HubAgent


# ============================================================
# 系统全景说明书 (注入到每个智能体)
# ============================================================

SYSTEM_OVERVIEW = """你是一个经验丰富的加密货币交易员，在 AutoTrade 系统中工作。

你可以通过工具查看行情、技术指标、账户余额、持仓情况，也可以直接下单交易。
你的交易指令会经过系统的风控层自动审核，不用担心杠杆过高或亏损过大的问题。

## 你的工作方式
像一个真实的人一样思考和说话。用中文。

当你查数据时，不要输出原始 JSON，用自然语言描述你看到了什么。比如:
- 不要说: get_price 返回 {"price": 65000}
- 要说: "我看了一下 BTC，现在 65000 美元，今天涨了 1%。"

当你分析时，说出你真实的想法，比如:
- "这个位置有点尴尬，上面有阻力，下面又有支撑，我倾向于先不动。"
- "RSI 都快 30 了，加上刚才一根放量长下影线，我觉得可以试试做多。"

不要被任何固定规则限制。你有自己的交易直觉和经验，根据实际盘面做判断。
老板只给你一个大方向（写在你的角色设定里），具体怎么操作由你自己决定。

## 注意事项
- 全程中文，说人话
- 简洁，不写长文
- 没把握就别动，说"我先看看"就行
- 禁止使用 Emoji"""


class HubBrain:
    """
    Hub AI 大脑
    
    负责：
    1. 为智能体组装完整的 messages
    2. 调用 AI 大模型
    3. 处理 tool_call → 执行工具 → 返回结果
    4. SSE 流式输出
    """
    
    async def chat_stream(
        self,
        agent: HubAgent,
        message: str,
        db: AsyncSession,
        user_id: int,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话 (SSE 事件生成器)
        
        Yields: JSON 字符串, 每个是一个 SSE 事件
        """
        # 1. 组装 system prompt
        full_system_prompt = self._build_system_prompt(agent)
        
        # 2. 构建 messages
        messages = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": message},
        ]
        
        # 3. 获取 AI client
        client = await self._get_client(agent, user_id, db)
        if not client:
            yield json.dumps({"type": "error", "content": "无法初始化 AI 客户端"})
            return
        
        # 4. 获取工具定义
        tools_spec = self._get_tools_spec()
        
        # 5. 调用 AI (支持多轮 tool_call)
        max_rounds = 15
        for round_idx in range(max_rounds):
            try:
                response = await client.chat.completions.create(
                    model=agent.model,
                    messages=messages,
                    tools=tools_spec if tools_spec else None,
                    temperature=agent.temperature,
                    stream=False,  # 先用非流式, 简化 tool_call 处理
                )
            except Exception as e:
                logger.error(f"[HubBrain] AI call failed: {e}")
                yield json.dumps({"type": "error", "content": f"AI 调用失败: {str(e)}"})
                return
            
            choice = response.choices[0]
            
            # 检查是否有 tool_call
            if choice.message.tool_calls:
                # 有工具调用
                messages.append(choice.message)
                
                for tc in choice.message.tool_calls:
                    tool_name = tc.function.name
                    try:
                        tool_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    yield json.dumps({
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_args,
                    })
                    
                    # 执行工具
                    tool_result = await self._execute_tool(
                        tool_name, tool_args, db, user_id,
                    )
                    
                    yield json.dumps({
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": tool_result,
                    })
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })
                
                # 继续下一轮 (让 AI 基于工具结果继续推理)
                continue
            
            else:
                # 无 tool_call, 返回文本
                content = choice.message.content or ""
                yield json.dumps({
                    "type": "text",
                    "content": content,
                })
                yield json.dumps({
                    "type": "done",
                    "content": content,
                })
                return
        
        yield json.dumps({"type": "done", "content": "[工具调用轮次已达上限]"})
    
    async def chat_once(
        self,
        agent: HubAgent,
        message: str,
        db: AsyncSession,
        user_id: int,
    ) -> str:
        """
        单次对话 (非流式, daemon 用)
        
        Returns: AI 的最终回复文本
        """
        full_reply = ""
        async for event_str in self.chat_stream(agent, message, db, user_id):
            event = json.loads(event_str)
            if event["type"] == "done":
                full_reply = event.get("content", "")
            elif event["type"] == "error":
                full_reply = f"[ERROR] {event.get('content', '')}"
        return full_reply
    
    def _build_system_prompt(self, agent: HubAgent) -> str:
        """组装完整的 system prompt"""
        parts = [SYSTEM_OVERVIEW]
        
        if agent.system_prompt:
            parts.append(f"\n## 你的专属角色指令\n{agent.system_prompt}")
        
        parts.append(f"\n## 你的身份\n- 名称: {agent.name}\n- 角色: {agent.role}")
        
        return "\n".join(parts)
    
    async def _get_client(self, agent: HubAgent, user_id: int, db: AsyncSession):
        """获取 OpenAI 兼容的 client"""
        import openai
        
        # 优先使用智能体独立配置
        api_key = None
        base_url = agent.api_base_url
        
        if agent.api_key_enc:
            try:
                from app.api.hub import _decrypt_key
                api_key = _decrypt_key(agent.api_key_enc)
            except Exception:
                pass
        
        # 如果智能体没有独立配置, 则读取用户全局配置
        if not api_key:
            from app.models.user_ai_config import UserAIConfig
            from sqlalchemy import select
            result = await db.execute(
                select(UserAIConfig).where(UserAIConfig.user_id == user_id)
            )
            user_config = result.scalar_one_or_none()
            if user_config and user_config.api_key_encrypted:
                try:
                    from app.core.encryption import decrypt_value
                    api_key = decrypt_value(user_config.api_key_encrypted)
                except Exception:
                    pass
                if not base_url:
                    base_url = user_config.api_base_url
        
        if not api_key:
            return None
        
        if not base_url:
            base_url = "https://api.deepseek.com"
        
        # 确保 base_url 以 /v1 结尾
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        
        return openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    
    def _get_tools_spec(self) -> list:
        """获取工具定义 (OpenAI function calling format)"""
        from app.services.agent.tools import TOOL_REGISTRY
        import inspect
        
        tools = []
        for name, func in TOOL_REGISTRY.items():
            # 从函数签名提取参数
            sig = inspect.signature(func)
            properties = {}
            required = []
            
            for param_name, param in sig.parameters.items():
                # 跳过系统注入参数
                if param_name in ("db", "user_id"):
                    continue
                
                # 类型推断
                annotation = param.annotation
                if annotation == int or annotation == float:
                    param_type = "number"
                elif annotation == bool:
                    param_type = "boolean"
                else:
                    param_type = "string"
                
                prop = {"type": param_type}
                
                if param.default != inspect.Parameter.empty:
                    prop["default"] = param.default
                else:
                    required.append(param_name)
                
                properties[param_name] = prop
            
            tool_def = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": func.__doc__ or name,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            tools.append(tool_def)
        
        return tools
    
    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict,
        db: AsyncSession,
        user_id: int,
    ) -> str:
        """执行工具并返回结果"""
        from app.services.agent.tools import TOOL_REGISTRY
        
        func = TOOL_REGISTRY.get(tool_name)
        if not func:
            return json.dumps({"error": f"未知工具: {tool_name}"})
        
        try:
            # 注入系统参数
            result = await func(db=db, user_id=user_id, **tool_args)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:
            logger.error(f"[HubBrain] Tool {tool_name} failed: {e}")
            return json.dumps({"error": str(e)})


# 全局单例
hub_brain = HubBrain()
