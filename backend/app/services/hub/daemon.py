"""
Hub Daemon — 智能体中枢守护进程
====================================
平行于 autopilot.py, 完全独立的调度器。

职责:
- 定时扫描 active 智能体
- 独裁者模式: 单 Agent 自主循环
- 董事会模式: 多 AI 辩论 → 执行共识

与 autopilot.py 的关系:
- 完全不修改 autopilot.py
- 智能体可通过 tools 调用 start_autopilot 间接使用老引擎
"""

import asyncio
from typing import Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hub_agent import HubAgent, HubAgentStatus
from app.core.time_utils import utc_now


class HubDaemon:
    """
    Hub 守护进程
    
    管理智能体的生命周期：启动、停止、循环执行
    """
    
    def __init__(self):
        self._agent_tasks: Dict[str, asyncio.Task] = {}  # key: "user_id:agent_id"
        self._running = False
    
    def _task_key(self, user_id: int, agent_id: int) -> str:
        return f"{user_id}:{agent_id}"
    
    async def start_agent(self, user_id: int, agent: HubAgent):
        """启动单个智能体的自主循环"""
        key = self._task_key(user_id, agent.id)
        
        # 如果已在运行, 先停止
        if key in self._agent_tasks:
            self._agent_tasks[key].cancel()
        
        task = asyncio.create_task(
            self._agent_loop(user_id, agent.id),
            name=f"hub_agent_{key}",
        )
        self._agent_tasks[key] = task
        logger.info(f"[HubDaemon] [STARTED] Agent #{agent.id} '{agent.name}' started for user {user_id}")
    
    async def stop_agent(self, user_id: int, agent_id: int):
        """停止单个智能体"""
        key = self._task_key(user_id, agent_id)
        task = self._agent_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"[HubDaemon] [STOPPED] Agent #{agent_id} stopped for user {user_id}")
    
    async def run_agent_once(
        self,
        user_id: int,
        agent: HubAgent,
        db: AsyncSession,
    ):
        """手动触发一次智能体执行"""
        await self._execute_cycle(user_id, agent, db)
    
    async def _agent_loop(self, user_id: int, agent_id: int):
        """单个智能体的自主循环"""
        interval = 300  # 默认5分钟, 会被 DB 字段覆盖
        consecutive_errors = 0
        MAX_CONSECUTIVE_FATAL = 3  # 连续致命错误 N 次后熔断
        
        # 不可恢复的致命关键词 (这些错误再重试也没用)
        FATAL_KEYWORDS = [
            'insufficient', 'balance', 'billing', 'quota', 'exceeded',
            'invalid api key', 'invalid_api_key', 'api key not valid',
            'account deactivated', 'account suspended', 'deactivated',
            'permission denied', 'forbidden',
        ]
        
        while True:
            try:
                from app.db.session import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    # 重新加载智能体状态
                    result = await db.execute(
                        select(HubAgent).where(HubAgent.id == agent_id)
                    )
                    agent = result.scalar_one_or_none()
                    
                    if not agent or not agent.is_active:
                        logger.info(f"[HubDaemon] Agent #{agent_id} no longer active, stopping loop")
                        break
                    
                    await self._execute_cycle(user_id, agent, db)
                    await db.commit()
                    
                    # ★ 动态轮询间隔: 从 DB 字段读取 (分钟 → 秒)
                    interval = max(agent.polling_interval or 5, 1) * 60
                    
                    # ★ 自愈机制: 成功执行后重置错误计数
                    consecutive_errors = 0
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                logger.info(f"[HubDaemon] Agent #{agent_id} loop cancelled")
                break
            except Exception as e:
                err_str = str(e).lower()
                err_detail = str(e)[:500]
                
                # 判断是否为致命错误 (不可自动恢复)
                is_fatal = any(kw in err_str for kw in FATAL_KEYWORDS)
                # 瞬态: timeout/连接/SSL 等
                is_transient = not is_fatal and any(kw in err_str for kw in [
                    '401', 'unauthorized', 'timeout', 'timed out',
                    'connect', 'connection', 'refused', 'reset',
                    'ssl', 'eof', 'broken pipe',
                ])
                
                if is_fatal:
                    consecutive_errors += 1
                
                # ★ 推送错误到 hub_logs (前端可见)
                try:
                    from app.db.session import AsyncSessionLocal
                    from app.models.hub_log import HubLog
                    async with AsyncSessionLocal() as err_db:
                        result = await err_db.execute(
                            select(HubAgent).where(HubAgent.id == agent_id)
                        )
                        agent = result.scalar_one_or_none()
                        agent_name = agent.name if agent else f"Agent #{agent_id}"
                        
                        if is_fatal:
                            log_content = f"[致命错误] {agent_name}: {err_detail}"
                        elif is_transient:
                            log_content = f"[瞬态错误] {agent_name}: {err_detail} (将自动重试)"
                        else:
                            log_content = f"[运行错误] {agent_name}: {err_detail}"
                        
                        err_db.add(HubLog(
                            user_id=user_id,
                            agent_id=agent_id,
                            agent_name=agent_name,
                            log_type="error",
                            content=log_content,
                        ))
                        
                        # 致命错误: 标红 + 熔断
                        if is_fatal and agent:
                            agent.status = HubAgentStatus.ERROR
                            agent.last_error = err_detail
                            # 连续致命错误超过阈值 → 彻底停止
                            if consecutive_errors >= MAX_CONSECUTIVE_FATAL:
                                agent.is_active = False
                                err_db.add(HubLog(
                                    user_id=user_id,
                                    agent_id=agent_id,
                                    agent_name=agent_name,
                                    log_type="error",
                                    content=f"[熔断] {agent_name} 连续 {consecutive_errors} 次致命错误，已自动挂起。请检查 API Key / 账户余额后手动重启。",
                                ))
                        elif not is_transient and agent:
                            agent.status = HubAgentStatus.ERROR
                            agent.last_error = err_detail
                        
                        await err_db.commit()
                except Exception as log_err:
                    logger.warning(f"[HubDaemon] Failed to save error log: {log_err}")
                
                # ★ 致命错误熔断: 真正停止循环
                if is_fatal and consecutive_errors >= MAX_CONSECUTIVE_FATAL:
                    logger.error(f"[HubDaemon] Agent #{agent_id} CIRCUIT BREAK: {consecutive_errors} consecutive fatal errors, stopping loop")
                    # 从运行列表中移除
                    key = self._task_key(user_id, agent_id)
                    self._agent_tasks.pop(key, None)
                    break
                
                if is_transient:
                    logger.warning(f"[HubDaemon] Agent #{agent_id} transient error (will retry): {e}")
                    await asyncio.sleep(15)
                    continue
                
                logger.error(f"[HubDaemon] Agent #{agent_id} loop error: {e}")
                await asyncio.sleep(30)
    
    async def _execute_cycle(
        self,
        user_id: int,
        agent: HubAgent,
        db: AsyncSession,
    ):
        """执行一个决策周期 (逐事件写入 hub_logs, 与手动触发完全对齐)"""
        from app.services.hub.brain import hub_brain
        import json as _json
        
        logger.info(f"[HubDaemon] [CYCLE] Agent #{agent.id} '{agent.name}' executing cycle")
        
        prompt = self._build_cycle_prompt(agent)
        
        # ★ 核心改造: 直接遍历 chat_stream, 逐事件推送到 hub_logs
        full_reply = ""
        has_error = False
        has_trade = False  # ★ 追踪是否产生了交易
        
        # ★ 交易检测关键词 — 在 tool_result 中检测更可靠
        TRADE_KEYWORDS = ["order_id", "订单已", "已下单", "已平仓", '"success": true', '"success":true', "Pipeline"]
        
        try:
            async for event_str in hub_brain.chat_stream(
                agent=agent,
                message=prompt,
                db=db,
                user_id=user_id,
            ):
                try:
                    event = _json.loads(event_str)
                except Exception:
                    continue
                
                ev_type = event.get("type", "")
                ev_content = event.get("content", "")
                
                # 跳过空事件和 ping
                if ev_type == "ping" or not ev_type:
                    continue
                
                if ev_type == "text" and ev_content:
                    # AI 思考输出 — 即时写入 hub_logs
                    await self._save_log(user_id, agent.id, agent.name, "ai_text", ev_content)
                
                elif ev_type == "tool_call":
                    # 工具调用 — 即时写入 hub_logs
                    tool_name = event.get("tool", "unknown")
                    tool_args = event.get("args", {})
                    args_str = _json.dumps(tool_args, ensure_ascii=False)[:200]
                    await self._save_log(user_id, agent.id, agent.name, "tool_call", f"[TOOL] {tool_name}({args_str})")
                    # ★ 检测交易工具调用
                    if tool_name in ("place_order", "close_position"):
                        has_trade = True  # 调用了下单/平仓工具
                
                elif ev_type == "tool_result":
                    # 工具结果 — 即时写入 hub_logs
                    result_str = event.get("result", str(ev_content))
                    result_preview = result_str[:300]
                    await self._save_log(user_id, agent.id, agent.name, "tool_result", f"[RESULT] {result_preview}")
                    # ★ 在 tool_result 中检测交易成功（比 full_reply 可靠得多）
                    if not has_trade and any(kw in result_str for kw in TRADE_KEYWORDS):
                        has_trade = True
                
                elif ev_type == "done":
                    full_reply = ev_content or ""
                    # ★ 兜底：也在 final reply 中检测
                    if not has_trade and any(kw in full_reply for kw in TRADE_KEYWORDS):
                        has_trade = True
                
                elif ev_type == "error":
                    has_error = True
                    full_reply = f"[ERROR] {ev_content}"
                    await self._save_log(user_id, agent.id, agent.name, "error", f"[ERROR] {ev_content}")
                    
        except Exception as e:
            has_error = True
            full_reply = f"[ERROR] AI 调用异常: {str(e)}"
            logger.error(f"[HubDaemon] Agent #{agent.id} stream exception: {e}")
            try:
                await self._save_log(user_id, agent.id, agent.name, "error", full_reply)
            except Exception:
                pass
        
        # 更新状态
        agent.total_runs += 1
        agent.last_run_at = utc_now()
        
        if has_error:
            agent.last_error = full_reply[:500]
        else:
            agent.last_error = None
            # ★ 自愈机制: 成功执行 → 从 error 恢复为 active
            if agent.status == HubAgentStatus.ERROR:
                agent.status = HubAgentStatus.ACTIVE
                logger.info(f"[HubDaemon] Agent #{agent.id} auto-healed: ERROR → ACTIVE")
                try:
                    await self._save_log(user_id, agent.id, agent.name, "system", f"[自愈] {agent.name} 已从错误状态恢复正常运行")
                except Exception:
                    pass
        
        # ★ 检查是否产生了交易 — 多层检测（tool_call 名称 + tool_result 内容 + final reply）
        if has_trade:
            agent.total_trades += 1
        
        logger.info(
            f"[HubDaemon] Agent #{agent.id} cycle done. "
            f"Runs={agent.total_runs}, Trades={agent.total_trades}"
            f"{' [TRADED]' if has_trade else ''}"
        )
    
    async def _save_log(
        self,
        user_id: int,
        agent_id: int,
        agent_name: str,
        log_type: str,
        content: str,
    ):
        """使用独立 session 即时写入一条 hub_log，确保前端轮询能实时看到"""
        from app.db.session import AsyncSessionLocal
        from app.models.hub_log import HubLog
        try:
            async with AsyncSessionLocal() as log_db:
                log_db.add(HubLog(
                    user_id=user_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    log_type=log_type,
                    content=content,
                ))
                await log_db.commit()
        except Exception as e:
            logger.warning(f"[HubDaemon] Failed to save log: {e}")
    
    def _build_cycle_prompt(self, agent: HubAgent) -> str:
        """构建自主决策周期的 prompt (开放式策略版)"""
        watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        symbols_str = "、".join(watchlist)
        
        return (
            f"轮到你值班了。你需要关注以下交易对: {symbols_str}。\n\n"
            "你拥有以下交易能力:\n"
            "- place_order: 开合约仓位（做多/做空）\n"
            "- close_position: 平仓\n"
            "- manage_grid: 管理网格交易（创建/启动/停止/查看）\n\n"
            "请自主完成以下工作:\n"
            "1. 查看当前持仓和已有网格 (manage_grid action='list')\n"
            f"2. 分析 {symbols_str} 的行情和技术指标\n"
            "3. 根据你对市场的判断，自主决定最合适的交易策略:\n"
            "   - 你认为适合趋势跟踪就开合约\n"
            "   - 你认为适合区间震荡就开网格\n"
            "   - 你认为需要观望就不操作\n"
            "   - 已有仓位或网格不合理时，主动调整或关闭\n"
            "4. 简要汇报你的判断和行动\n\n"
            "注意: 调用工具时请明确指定 symbol 参数。风控原则: 单笔投入不超过账户余额的 30%。"
        )
    
    def get_running_agents(self) -> list:
        """获取当前运行中的智能体列表"""
        return [
            key for key, task in self._agent_tasks.items()
            if not task.done()
        ]


# 全局单例
hub_daemon = HubDaemon()
