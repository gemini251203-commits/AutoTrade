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

## 效率原则 (极重要 — 直接影响运营成本)
- 你可以一次调用多个工具! 比如同时查 BTC、ETH、SOL 的价格，不要一个一个查
- **禁止逐个查询**: 需要查多个币种时，必须在同一轮同时调用，例如:
  同时调 get_price(symbol=BTCUSDT) + get_price(symbol=ETHUSDT) + get_price(symbol=SOLUSDT)
  而不是先查 BTC，等结果，再查 ETH，再等结果...
- 同理，get_indicators、get_funding_rate 等也要一次性批量调用
- 如果市场和上次看的差不多，简单说"变化不大"即可，不需要重复完整分析
- 回复控制在 200 字以内，观望时 100 字以内即可

## 注意事项
- 全程中文，说人话
- 简洁，不写长文
- 没把握就别动，说"我先看看"就行
- 你有记忆，能想起之前说过什么、做过什么。如果情况和上次差不多，可以说"跟刚才差不多"
- 禁止使用 Emoji

## 智能唤醒机制
你可以在每次分析结束后，使用 set_wake_conditions 工具设定唤醒条件。
系统会在后台持续监控这些条件，满足时立即唤醒你进行分析，而不必等到下一次固定轮询。

可用条件类型:
- price_above: 价格突破上方 (如 BTC > 88000)
- price_below: 价格跌破下方 (如 BTC < 82000)
- change_pct: 价格离当前基准变化超过百分比 (如 ±2%)

注意: 条件采用 OR 逻辑，任一条件满足即触发唤醒。
设定示例: 你认为 BTC 在 85000-88000 区间震荡，可以同时设 price_above BTC>88000 和 price_below BTC<85000，任一触发即唤醒。
每次分析完市场后，根据你识别的关键位设定合理的唤醒条件。"""


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
        
        # 1.5 注入董事会共享记忆 (近期纪要)
        try:
            from app.services.hub.consolidator import load_board_memory
            board_mem = await load_board_memory(db, user_id, days=7)
            if board_mem:
                full_system_prompt += f"\n\n## 董事会共享记忆 (近7天纪要)\n{board_mem}"
                full_system_prompt += (
                    "\n\n> 💡 提示: 以上是近7天的\"热记忆\"。如果你遇到罕见的极端行情，"
                    "或需要更久远的历史经验，请主动调用 search_historical_minutes 工具，"
                    "搜索过去数月的董事会纪要（冷记忆）。"
                )
        except Exception as e:
            logger.warning(f"[HubBrain] Board memory injection failed: {e}")
        
        # 1.55 注入 mem0 深层记忆 (语义搜索历史经验)
        try:
            from app.services.hub.memory_service import get_relevant_context
            deep_mem = await get_relevant_context(user_id, message, limit=3)
            if deep_mem:
                full_system_prompt += f"\n\n{deep_mem}"
        except Exception as e:
            logger.debug(f"[HubBrain] Deep memory injection skipped: {e}")
        
        # 1.6 注入全体 Agent 共享上下文 (打破平行宇宙)
        try:
            shared_ctx = await self._load_shared_context(db, user_id, agent.id)
            if shared_ctx:
                full_system_prompt += shared_ctx
        except Exception as e:
            logger.warning(f"[HubBrain] Shared context injection failed: {e}")
        
        # 2. 加载记忆 (从 hub_logs 获取近期对话历史)
        memory_messages = await self._load_memory(db, user_id, agent.id)
        
        # 3. 构建 messages (system + 记忆 + 当前消息)
        messages = [
            {"role": "system", "content": full_system_prompt},
            *memory_messages,
            {"role": "user", "content": message},
        ]
        
        # 3. 获取 AI client
        client = await self._get_client(agent, user_id, db)
        if not client:
            yield json.dumps({"type": "error", "content": "无法初始化 AI 客户端"})
            return
        
        # 4. 获取工具定义 (根据 agent 的 allowed_tools 过滤)
        tools_spec = self._get_tools_spec(allowed_tools=agent.allowed_tools)
        
        # 5. 调用 AI (支持多轮 tool_call)
        max_rounds = 30
        for round_idx in range(max_rounds):
            try:
                response = await client.chat.completions.create(
                    model=agent.model,
                    messages=messages,
                    tools=tools_spec if tools_spec else None,
                    temperature=agent.temperature,
                    max_tokens=8192,  # ★ 确保充足的输出空间，避免半句截断
                    stream=False,  # 先用非流式, 简化 tool_call 处理
                )
            except Exception as e:
                logger.error(f"[HubBrain] AI call failed: {e}")
                yield json.dumps({"type": "error", "content": f"AI 调用失败: {str(e)}"})
                return
            
            choice = response.choices[0]
            finish_reason = choice.finish_reason  # ★ 检测截断
            
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
                    
                    # 执行工具 (传入 allowed_tools 进行授权检查)
                    tool_result = await self._execute_tool(
                        tool_name, tool_args, db, user_id,
                        allowed_tools=agent.allowed_tools,
                        agent_name=agent.name,
                    )
                    
                    yield json.dumps({
                        "type": "tool_result",
                        "tool": tool_name,
                        "result": tool_result,
                    })
                    
                    # ★ 压缩工具结果再喂给 AI (前端已收到完整结果)
                    from app.services.hub.tool_compressor import compress_tool_result
                    compressed_result = compress_tool_result(tool_name, tool_result)
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": compressed_result,
                    })
                
                # ★ Phase 5: 滑动窗口 — 防止 messages 无限膨胀
                self._apply_sliding_window(messages, max_tool_messages=8)
                
                # 继续下一轮 (让 AI 基于工具结果继续推理)
                continue
            
            else:
                # 无 tool_call, 返回文本
                content = choice.message.content or ""
                
                # ★ 处理 finish_reason=length (输出被截断)
                if finish_reason == "length" and content:
                    logger.warning(
                        f"[HubBrain] Output truncated (finish_reason=length), "
                        f"attempting continuation... ({len(content)} chars so far)"
                    )
                    full_content = content
                    cont_messages = messages + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": "你的回复被截断了，请从断点处继续说完。不要重复已说过的内容。"},
                    ]
                    
                    for cont_idx in range(3):
                        try:
                            cont_resp = await client.chat.completions.create(
                                model=agent.model,
                                messages=cont_messages,
                                tools=None,
                                temperature=agent.temperature,
                                max_tokens=8192,
                                stream=False,
                            )
                            cont_choice = cont_resp.choices[0]
                            cont_text = cont_choice.message.content or ""
                            if cont_text:
                                full_content += cont_text
                            if cont_choice.finish_reason != "length":
                                break
                            cont_messages.append({"role": "assistant", "content": cont_text})
                            cont_messages.append({"role": "user", "content": "继续。"})
                        except Exception as e:
                            logger.error(f"[HubBrain] Continuation failed: {e}")
                            break
                    
                    content = full_content
                
                yield json.dumps({
                    "type": "text",
                    "content": content,
                })
                yield json.dumps({
                    "type": "done",
                    "content": "",
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
            if event["type"] == "text":
                full_reply += event.get("content", "")
            elif event["type"] == "error":
                full_reply = f"[ERROR] {event.get('content', '')}"
        return full_reply
    
    async def _load_memory(
        self,
        db: AsyncSession,
        user_id: int,
        agent_id: int,
        max_entries: int = 20,
    ) -> list:
        """
        加载 AI 的记忆 (从 hub_logs 读取近期对话历史)
        
        将历史日志重构为 user/assistant 消息对，
        让 AI 记住自己之前做了什么、说了什么。
        """
        try:
            from app.models.hub_log import HubLog
            from sqlalchemy import select
            
            query = (
                select(HubLog)
                .where(
                    HubLog.user_id == user_id,
                    HubLog.agent_id == agent_id,
                    HubLog.log_type.in_(["system", "ai_text"]),
                )
                .order_by(HubLog.created_at.desc())
                .limit(max_entries)
            )
            result = await db.execute(query)
            logs = list(reversed(result.scalars().all()))
            
            if not logs:
                return []
            
            # 重构为对话消息
            memory = []
            for log in logs:
                if log.log_type == "system" and log.content.startswith("[CMD]"):
                    # 用户指令 → user message
                    cmd_text = log.content.replace("[CMD] ", "").strip()
                    if cmd_text:
                        memory.append({"role": "user", "content": cmd_text})
                elif log.log_type == "system" and log.content.startswith("[TRIGGER]"):
                    # 值班触发 → user message
                    memory.append({"role": "user", "content": "轮到你值班了，看看市场情况。"})
                elif log.log_type == "ai_text":
                    # AI 回复 → assistant message
                    memory.append({"role": "assistant", "content": log.content})
            
            # 清理: 确保不以 user 结尾 (当前消息会补上)
            # 也确保不超过 token 限制 (粗略估计)
            total_chars = sum(len(m["content"]) for m in memory)
            while total_chars > 3000 and memory:
                removed = memory.pop(0)
                total_chars -= len(removed["content"])
            
            if memory:
                logger.info(f"[HubBrain] Loaded {len(memory)} memory entries for agent #{agent_id}")
            
            return memory
            
        except Exception as e:
            logger.warning(f"[HubBrain] Failed to load memory: {e}")
            return []
    
    def _build_system_prompt(self, agent: HubAgent) -> str:
        """组装完整的 system prompt"""
        parts = [SYSTEM_OVERVIEW]
        
        if agent.system_prompt:
            parts.append(f"\n## 你的专属角色指令\n{agent.system_prompt}")
        
        parts.append(f"\n## 你的身份\n- 名称: {agent.name}\n- 角色: {agent.role}")
        
        return "\n".join(parts)
    
    async def _load_shared_context(
        self,
        db: AsyncSession,
        user_id: int,
        current_agent_id: int,
        max_entries: int = 15,
    ) -> str:
        """
        加载全体 Agent 的近期动态 (打破平行宇宙)
        
        从 hub_logs 中捞取所有 Agent（排除自己）的对话和动作，
        拼装为"会议室实时动态"注入到 system prompt。
        """
        try:
            from app.models.hub_log import HubLog
            from sqlalchemy import select
            
            query = (
                select(HubLog)
                .where(
                    HubLog.user_id == user_id,
                    HubLog.agent_id != current_agent_id,  # 排除自己
                    HubLog.log_type.in_(["ai_text", "error", "system"]),
                )
                .order_by(HubLog.created_at.desc())
                .limit(max_entries)
            )
            result = await db.execute(query)
            logs = list(reversed(result.scalars().all()))
            
            if not logs:
                return ""
            
            lines = []
            for log in logs:
                name = log.agent_name or f"Agent #{log.agent_id}"
                content = log.content[:200]
                # 格式: "[Alpha猎手] 我看了下BTC, 67000附近有阻力..."
                lines.append(f"[{name}] {content}")
            
            if not lines:
                return ""
            
            shared = "\n".join(lines)
            logger.info(
                f"[HubBrain] Injected {len(lines)} shared context entries "
                f"for agent #{current_agent_id}"
            )
            return (
                "\n\n## 会议室实时动态\n"
                "以下是你的同事们最近的发言和动作，你可以参考、接话或反驳：\n"
                f"{shared}"
            )
            
        except Exception as e:
            logger.warning(f"[HubBrain] Failed to load shared context: {e}")
            return ""
    
    def _apply_sliding_window(self, messages: list, max_tool_messages: int = 8):
        """
        Phase 5: 滑动窗口 — 防止多轮工具调用导致 messages 无限膨胀
        
        当 messages 中的 tool role 消息超过 max_tool_messages 条时，
        将较旧的 tool 消息内容原地截断为简短摘要。
        
        ★ 关键设计: 不删除任何消息，只截断内容。
        因为删除 assistant(tool_calls) 消息会导致其对应的 tool 消息变成"孤儿"，
        触发 OpenAI API 400 错误: "Messages with role 'tool' must be a response 
        to a preceding message with 'tool_calls'"。
        
        注意: 此方法直接修改传入的 messages 列表 (in-place)。
        """
        # 统计 tool role 消息数量
        tool_indices = [
            i for i, m in enumerate(messages)
            if isinstance(m, dict) and m.get("role") == "tool"
        ]
        
        if len(tool_indices) <= max_tool_messages:
            return  # 不需要压缩
        
        # 需要压缩的 tool 消息: 除了最近 max_tool_messages 条外的所有
        to_compress_indices = tool_indices[:-max_tool_messages]
        compressed_count = 0
        
        for tool_idx in to_compress_indices:
            msg = messages[tool_idx]
            content = msg.get("content", "")
            
            # 已经是压缩过的，跳过
            if content.startswith("[已压缩]"):
                continue
            
            # 原地截断内容 (保留前 60 字符作为摘要)
            summary = content[:60].replace("\n", " ")
            if len(content) > 60:
                summary += "..."
            msg["content"] = f"[已压缩] {summary}"
            compressed_count += 1
        
        if compressed_count > 0:
            logger.info(
                f"[HubBrain] Sliding window: truncated {compressed_count} old tool results in-place"
            )
    
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
                    from app.core.encryption import decrypt_api_key
                    api_key = decrypt_api_key(user_config.api_key_encrypted)
                except Exception:
                    pass
                if not base_url:
                    base_url = user_config.api_base_url
        
        if not api_key:
            # Ollama / custom 本地模型通常不需要 API key
            if agent.provider in ('ollama', 'custom') and base_url:
                api_key = "ollama"  # placeholder
            else:
                return None
        
        if not base_url:
            # 根据供应商选择默认 Base URL (仅当用户未自定义时)
            _PROVIDER_URLS = {
                'deepseek': 'https://api.deepseek.com',
                'openai': 'https://api.openai.com',
                'ollama': 'http://localhost:11434',
            }
            base_url = _PROVIDER_URLS.get(agent.provider, 'https://api.deepseek.com')
        
        # 注意: 不再强制追加 /v1
        # OpenAI SDK 会自动处理路径, 用户自定义 URL 不应被修改
        # (例如 Google Gemini: https://generativelanguage.googleapis.com/v1beta/openai/)
        
        return openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    
    # 系统必备工具 — 不受 allowed_tools 过滤，始终对 AI 可用
    _SYSTEM_TOOLS = {"set_wake_conditions"}
    
    def _get_tools_spec(self, allowed_tools: list | None = None) -> list:
        """获取工具定义 (OpenAI function calling format)
        
        Args:
            allowed_tools: 授权工具列表.
                None = 全部工具可用 (默认/向后兼容)
                [] = 禁用所有工具
                ['get_price', 'place_order'] = 仅指定工具
        """
        from app.services.agent.tools import TOOL_REGISTRY
        import inspect
        
        tools = []
        for name, func in TOOL_REGISTRY.items():
            # 🔒 权限过滤: 如果 allowed_tools 不为 None, 只保留列表内的工具
            # ★ 系统必备工具 (如 set_wake_conditions) 始终可用，不受过滤
            if allowed_tools is not None and name not in allowed_tools and name not in self._SYSTEM_TOOLS:
                continue
            
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
        allowed_tools: list | None = None,
        agent_name: str = "",
    ) -> str:
        """执行工具并返回结果"""
        from app.services.agent.tools import TOOL_REGISTRY, agent_source_var, agent_name_var
        
        # 🔒 授权检查: 拒绝未授权的工具调用
        # ★ 系统必备工具始终放行
        if allowed_tools is not None and tool_name not in allowed_tools and tool_name not in self._SYSTEM_TOOLS:
            logger.warning(f"[HubBrain] Tool '{tool_name}' blocked by allowed_tools policy")
            return json.dumps({"error": f"工具 '{tool_name}' 未授权，请在 Agent 配置中启用"})
        
        # 设置来源为 hub，让交易日志正确标注
        agent_source_var.set('hub')
        # ★ 设置 Agent 名称，用于订单归属追踪
        if agent_name:
            agent_name_var.set(agent_name)
        
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
