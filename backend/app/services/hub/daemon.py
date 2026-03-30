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
from datetime import datetime, timezone
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
        
        wake_reason = ""  # 上次唤醒原因 (传给下一轮 prompt)
        
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
                    
                    # ★ 设置 Redis 上下文: 让 tools.py 中的 set_wake_conditions 知道当前 agent_id
                    await self._set_current_agent_context(user_id, agent_id)
                    
                    # ★ Phase 4: 智能跳过 — 市场无显著变化时跳过 AI 调用
                    should_skip, skip_reason = await self._should_skip_cycle(user_id, agent_id)
                    if should_skip:
                        logger.info(f"[HubDaemon] Agent #{agent_id} SKIPPED: {skip_reason}")
                        try:
                            await self._save_log(
                                user_id, agent_id, agent.name,
                                "system", f"[跳过] {skip_reason}",
                            )
                        except Exception:
                            pass
                    else:
                        await self._execute_cycle(user_id, agent, db, wake_reason=wake_reason)
                        wake_reason = ""  # 消费后清空
                    await db.commit()
                    
                    # ★ 分时巡逻策略: 根据时段动态调整轮询间隔
                    base_interval = max(agent.polling_interval or 5, 1) * 60
                    period, multiplier = self._get_time_period()
                    interval = int(base_interval * multiplier)
                    
                    logger.info(
                        f"[HubDaemon] Agent #{agent_id} next cycle in {interval}s "
                        f"(base={base_interval}s × {multiplier} [{period}])"
                    )
                    
                    # ★ 自愈机制: 成功执行后重置错误计数
                    consecutive_errors = 0
                
                # ★ 事件驱动唤醒: 在固定间隔等待期间，每 10 秒检查唤醒条件
                event_triggered, trigger_reason = await self._wait_with_wake_check(
                    user_id, agent_id, interval
                )
                if event_triggered:
                    wake_reason = trigger_reason
                    logger.info(
                        f"[HubDaemon] Agent #{agent_id} EVENT WAKE: {trigger_reason}"
                    )
                    # 写入系统日志 (前端可见)
                    try:
                        await self._save_log(
                            user_id, agent_id, agent.name if agent else f"Agent #{agent_id}",
                            "system", f"[事件唤醒] {trigger_reason}",
                        )
                    except Exception:
                        pass
                
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
        wake_reason: str = "",
    ):
        """执行一个决策周期 (逐事件写入 hub_logs, 与手动触发完全对齐)"""
        from app.services.hub.brain import hub_brain
        import json as _json
        
        logger.info(f"[HubDaemon] [CYCLE] Agent #{agent.id} '{agent.name}' executing cycle")
        
        prompt = self._build_cycle_prompt(agent, wake_reason=wake_reason)
        
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
        
        # ★ Phase 4: 执行后更新市场快照 (供下轮跳过判断)
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                cache_key = f"hub:snapshot:{user_id}:{agent.id}"
                skip_count_key = f"hub:skip_count:{user_id}:{agent.id}"
                await self._update_market_snapshot(r, cache_key, skip_count_key)
            finally:
                await r.aclose()
        except Exception:
            pass
        
        logger.info(
            f"[HubDaemon] Agent #{agent.id} cycle done. "
            f"Runs={agent.total_runs}, Trades={agent.total_trades}"
            f"{'  [TRADED]' if has_trade else ''}"
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
    
    @staticmethod
    def _get_time_period() -> tuple:
        """
        获取当前交易时段和对应的轮询倍率
        
        Returns:
            (时段名称, 间隔倍率)
            - 活跃时段 (UTC 8-16, 北京16-24): ×1.0
            - 平静时段 (UTC 16-0, 北京0-8):   ×1.5
            - 亚盘时段 (UTC 0-8, 北京8-16):   ×2.0
        """
        hour = datetime.now(timezone.utc).hour
        if 8 <= hour < 16:
            return "活跃", 1.0
        elif 16 <= hour < 24:
            return "平静", 1.5
        else:  # 0-8
            return "亚盘", 2.0
    
    def _build_cycle_prompt(self, agent: HubAgent, wake_reason: str = "") -> str:
        """构建自主决策周期的 prompt (开放式策略版 + 分时深度 + 唤醒条件)"""
        watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        symbols_str = "、".join(watchlist)
        
        # 分时分析深度
        period, _ = self._get_time_period()
        if period == "活跃":
            depth_hint = "当前为活跃交易时段(欧美盘)，请全面分析所有币种。"
        elif period == "平静":
            depth_hint = "当前为平静时段，只关注有显著变化的币种，其余简要带过。"
        else:
            depth_hint = "当前为亚盘时段(波动较小)，快速扫描即可，无异常直接汇报'市场平稳'。"
        
        # 唤醒原因提示
        wake_hint = ""
        if wake_reason:
            wake_hint = (
                f"\n\n🔔 本次是事件触发唤醒: {wake_reason}\n"
                "请重点分析触发条件相关的币种和价格位置。\n"
            )
        
        return (
            f"轮到你值班了。你需要关注以下交易对: {symbols_str}。\n"
            f"📊 时段: {period} — {depth_hint}"
            f"{wake_hint}\n\n"
            "你拥有以下交易能力:\n"
            "- place_order: 开合约仓位（做多/做空）\n"
            "- close_position: 平仓\n"
            "- change_leverage: 修改持仓杠杆倍数（1-125倍，持仓中可调）\n"
            "- manage_grid: 管理网格交易（创建/启动/停止/查看）\n\n"
            "⚡ 效率要求 (必须遵守):\n"
            f"- 一次性同时查询所有币种! 同一轮并行调用 get_price/get_indicators，禁止逐个查!\n"
            "- 当前持仓+已有网格也是在同一轮查完\n"
            "- 总结分析控制在 200 字以内，观望时 100 字以内\n\n"
            "请自主完成以下工作:\n"
            "1. 查看当前持仓和已有网格 (manage_grid action='list')\n"
            f"2. 分析 {symbols_str} 的行情和技术指标\n"
            "3. 根据你对市场的判断，自主决定最合适的交易策略:\n"
            "   - 你认为适合趋势跟踪就开合约\n"
            "   - 你认为适合区间震荡就开网格\n"
            "   - 你认为需要观望就不操作\n"
            "   - 已有仓位或网格不合理时，主动调整或关闭\n"
            "4. 简要汇报你的判断和行动\n"
            "5. 分析结束后，请用 set_wake_conditions 工具设定唤醒条件:\n"
            "   - 根据你对关键支撑/阻力位的判断，设定价格突破/跌破条件\n"
            "   - 条件示例: BTC 突破某阻力位 或 跌破某支撑位\n"
            "   - 设定合理的超时时间 (10-60 分钟)\n"
            "   - 如果市场波动剧烈，设更紧的条件; 市场无聊时设更宽松的条件\n\n"
            "注意: 调用工具时请明确指定 symbol 参数。风控原则: 单笔投入不超过账户余额的 30%，网格杠杆使用 10-20 倍，合约杠杆使用 10-15 倍。"
        )
    
    def get_running_agents(self) -> list:
        """获取当前运行中的智能体列表"""
        return [
            key for key, task in self._agent_tasks.items()
            if not task.done()
        ]
    
    # ============================================================
    # Phase 4: 智能跳过 — 市场快照比对
    # ============================================================
    
    # 跳过阈值: 所有关注币种的价格变化百分比均低于此值时跳过
    SKIP_THRESHOLD_PCT = 0.3  # 0.3%
    # 连续跳过上限: 避免长时间不调用 AI
    MAX_CONSECUTIVE_SKIPS = 3
    
    async def _should_skip_cycle(self, user_id: int, agent_id: int) -> tuple:
        """
        判断本轮是否可以跳过 AI 调用
        
        逻辑:
        1. 从 Redis 读取上轮价格快照
        2. 获取当前 BTC/ETH 价格
        3. 如果变化 < 阈值 且 连续跳过次数 < 上限 → 跳过
        
        Returns:
            (should_skip: bool, reason: str)
        """
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings
            
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            cache_key = f"hub:snapshot:{user_id}:{agent_id}"
            skip_count_key = f"hub:skip_count:{user_id}:{agent_id}"
            
            try:
                # 读取上轮快照
                import json as _json
                snapshot_raw = await r.get(cache_key)
                if not snapshot_raw:
                    # 首次运行, 无快照, 不跳过
                    await self._update_market_snapshot(r, cache_key, skip_count_key)
                    return False, ""
                
                old_snapshot = _json.loads(snapshot_raw)
                
                # 检查连续跳过次数
                skip_count = int(await r.get(skip_count_key) or 0)
                if skip_count >= self.MAX_CONSECUTIVE_SKIPS:
                    # 超过连续跳过上限, 强制执行
                    await self._update_market_snapshot(r, cache_key, skip_count_key)
                    return False, ""
                
                # 获取当前价格
                from app.services.market_collector import market_collector
                symbols = ["BTCUSDT", "ETHUSDT"]
                max_change = 0.0
                
                for sym in symbols:
                    price_data = market_collector.get_price(sym)
                    if not price_data or not price_data.get("price"):
                        # 获取不到价格, 不跳过
                        await self._update_market_snapshot(r, cache_key, skip_count_key)
                        return False, ""
                    
                    current = float(price_data["price"])
                    old_price = old_snapshot.get(sym, 0)
                    
                    if old_price > 0:
                        change_pct = abs(current - old_price) / old_price * 100
                        max_change = max(max_change, change_pct)
                
                if max_change < self.SKIP_THRESHOLD_PCT:
                    # 市场平稳, 跳过
                    await r.incr(skip_count_key)
                    await r.expire(skip_count_key, 7200)  # 2小时过期
                    return True, f"市场平稳 (最大变化 {max_change:.2f}% < {self.SKIP_THRESHOLD_PCT}%, 连续跳过 {skip_count + 1})"
                
                # 有变化, 更新快照并执行
                await self._update_market_snapshot(r, cache_key, skip_count_key)
                return False, ""
                
            finally:
                await r.aclose()
                
        except Exception as e:
            logger.debug(f"[HubDaemon] Skip check failed (will execute): {e}")
            return False, ""
    
    async def _update_market_snapshot(self, redis_client, cache_key: str, skip_count_key: str):
        """更新 Redis 中的市场价格快照"""
        import json as _json
        try:
            from app.services.market_collector import market_collector
            snapshot = {}
            for sym in ["BTCUSDT", "ETHUSDT"]:
                price_data = market_collector.get_price(sym)
                if price_data and price_data.get("price"):
                    snapshot[sym] = float(price_data["price"])
            
            if snapshot:
                await redis_client.set(cache_key, _json.dumps(snapshot), ex=3600)  # 1小时过期
                await redis_client.set(skip_count_key, 0, ex=7200)
        except Exception as e:
            logger.debug(f"[HubDaemon] Snapshot update failed: {e}")


    # ============================================================
    # 事件驱动唤醒: 辅助方法
    # ============================================================
    
    async def _wait_with_wake_check(
        self,
        user_id: int,
        agent_id: int,
        total_wait: int,
    ) -> tuple:
        """
        在固定间隔等待期间, 每 10 秒检查唤醒条件。
        条件满足时立即返回, 否则等到 total_wait 后正常返回。
        
        Args:
            total_wait: 总等待时间 (秒)
        
        Returns:
            (event_triggered: bool, reason: str)
        """
        from app.services.hub.wake_monitor import wake_monitor
        
        CHECK_INTERVAL = 10  # 每 10 秒检查一次
        elapsed = 0
        
        while elapsed < total_wait:
            sleep_time = min(CHECK_INTERVAL, total_wait - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time
            
            # 检查唤醒条件
            try:
                triggered, reason = await wake_monitor.check_conditions(user_id, agent_id)
                if triggered:
                    # 清除已触发的条件
                    await wake_monitor.clear_conditions(user_id, agent_id)
                    logger.info(
                        f"[HubDaemon] WakeMonitor TRIGGERED for #{agent_id}: {reason} "
                        f"(after {elapsed}s / {total_wait}s)"
                    )
                    return True, reason
            except Exception as e:
                logger.debug(f"[HubDaemon] Wake check error (ignored): {e}")
        
        return False, ""
    
    async def _set_current_agent_context(self, user_id: int, agent_id: int):
        """
        在 Redis 中设置当前正在执行的 agent_id 上下文。
        让 tools.py 中的 set_wake_conditions 工具能获取到正确的 agent_id。
        """
        try:
            import redis.asyncio as aioredis
            from app.core.config import settings
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            try:
                await r.set(
                    f"hub:current_agent:{user_id}",
                    str(agent_id),
                    ex=3600,  # 1 小时过期
                )
            finally:
                await r.aclose()
        except Exception as e:
            logger.debug(f"[HubDaemon] Failed to set agent context: {e}")


# 全局单例
hub_daemon = HubDaemon()
