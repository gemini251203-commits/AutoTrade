"""
Agent Autopilot (Enhanced)
============================
AI Agent 自动交易模式 — 增强版

功能:
- 定时触发 Agent 分析市场并决策
- 决策记录写入 AutopilotLog (结构化)
- 复用 Agent 完整工具链 (get_price, place_order, etc.)
- 支持多交易对同时监控
- 每次周期记录: 思考过程 + 决策 + 操作
"""

import asyncio
import json
import re
from typing import Dict, Optional, List
from datetime import datetime, timezone
from app.core.time_utils import utc_now

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.session import AsyncSessionLocal
from app.models.agent import ChatConversation, ChatMessage
from app.models.autopilot_log import AutopilotLog, AutopilotDecision
from app.models.strategy import Strategy
from app.services.agent.agent import chat_complete
from app.core.constants import INTERVAL_SECONDS

# Autopilot 会话标识前缀
AUTOPILOT_TITLE_PREFIX = "[autopilot]"

# 决策关键词映射
DECISION_KEYWORDS = {
    AutopilotDecision.OPEN_LONG: [
        "开多", "做多", "买入开仓", "open_long", "open long",
        "建仓做多",
    ],
    AutopilotDecision.OPEN_SHORT: [
        "开空", "做空", "卖出开仓", "open_short", "open short",
        "建仓做空",
    ],
    AutopilotDecision.CLOSE_LONG: [
        "平多", "多仓平仓", "close_long", "close long",
    ],
    AutopilotDecision.CLOSE_SHORT: [
        "平空", "空仓平仓", "close_short", "close short",
    ],
    AutopilotDecision.HOLD: [
        "观望", "等待", "不操作", "hold", "wait", "no action",
        "暂不交易", "保持观望",
    ],
}


def parse_decision(ai_reply: str) -> AutopilotDecision:
    """从 AI 回复中解析决策类型 (只匹配最后3行，避免分析描述干扰)"""
    lines = ai_reply.strip().split("\n")

    # 优先匹配 "决策：xxx" 格式
    for line in reversed(lines):
        clean = line.strip()
        decision_match = re.search(r"[决策决定][:：]\s*(.+)", clean)
        if decision_match:
            decision_text = decision_match.group(1).lower()
            for decision in [
                AutopilotDecision.HOLD,
                AutopilotDecision.OPEN_LONG,
                AutopilotDecision.OPEN_SHORT,
                AutopilotDecision.CLOSE_LONG,
                AutopilotDecision.CLOSE_SHORT,
            ]:
                for keyword in DECISION_KEYWORDS[decision]:
                    if keyword.lower() in decision_text:
                        return decision

    # fallback: 只看最后3行
    last_lines = "\n".join(lines[-3:]).lower()
    for decision in [
        AutopilotDecision.HOLD,
        AutopilotDecision.OPEN_LONG,
        AutopilotDecision.OPEN_SHORT,
        AutopilotDecision.CLOSE_LONG,
        AutopilotDecision.CLOSE_SHORT,
    ]:
        for keyword in DECISION_KEYWORDS[decision]:
            if keyword.lower() in last_lines:
                return decision

    # 检查是否调用了 place_order 工具 (全文检查)
    if "place_order" in ai_reply.lower():
        if "buy" in ai_reply.lower() or "做多" in ai_reply.lower():
            return AutopilotDecision.OPEN_LONG
        elif "sell" in ai_reply.lower() or "做空" in ai_reply.lower():
            return AutopilotDecision.OPEN_SHORT

    if "close_position" in ai_reply.lower():
        return AutopilotDecision.CLOSE_LONG

    return AutopilotDecision.HOLD


def extract_summary(ai_reply: str) -> str:
    """从 AI 回复中提取一句话摘要"""
    # 尝试提取第一个完整句子
    lines = ai_reply.strip().split("\n")
    for line in lines:
        clean = line.strip().lstrip("#").lstrip("-").lstrip("*").strip()
        if not clean or len(clean) <= 5:
            continue
        if clean.startswith("[TOOL_CALL"):
            continue
        # 跳过工具调用计数行，如 "[执行了 4 个操作]" 或 "执行了 4 个操作"
        if "执行了" in clean and "个操作" in clean:
            continue
        return clean[:200]
    return ai_reply[:200] if ai_reply else "无摘要"


def check_action_taken(ai_reply: str) -> bool:
    """检查 AI 是否实际做出了交易决策 (非观望)"""
    action_keywords = [
        "place_order", "close_position",
        "订单已创建", "下单成功", "开仓成功", "平仓成功",
        "order_id", "已执行",
        "trade_signal",  # 新的信号格式
    ]
    text = ai_reply.lower()
    return any(kw.lower() in text for kw in action_keywords)


def extract_order_id(ai_reply: str) -> Optional[int]:
    """从 AI 回复中提取订单 ID"""
    patterns = [
        r"order_id[\"']?\s*[:=]\s*(\d+)",
        r"订单.*?ID\s*[:：]\s*(\d+)",
        r'"id"\s*:\s*(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, ai_reply, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


class AgentAutopilot:
    """
    Agent 自动交易引擎 (增强版)

    - 多交易对支持
    - 结构化决策日志
    - 详细状态跟踪
    """

    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._configs: Dict[int, dict] = {}
        self._stats: Dict[int, dict] = {}  # 运行统计
        self._manually_stopped: set = set()  # 手动停止的用户, scheduler 不自动重启

    def is_running(self, user_id: int) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

    async def start(self, user_id: int, config: dict):
        """
        启动自动决策循环

        Args:
            config: {
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "interval": "15m",
            }
        """
        if self.is_running(user_id):
            logger.warning(f"[Autopilot] Already running for user {user_id}")
            return

        # 手动启动时清除手动停止标记
        self._manually_stopped.discard(user_id)

        self._configs[user_id] = config
        self._stats[user_id] = {
            "started_at": utc_now().isoformat(),
            "total_cycles": 0,
            "last_cycle_at": None,
            "actions_taken": 0,
        }
        task = asyncio.create_task(self._loop(user_id, config))
        self._tasks[user_id] = task
        logger.info(
            f"[Autopilot] Started for user {user_id}, "
            f"symbols={config.get('symbols')}, "
            f"interval={config.get('interval', '15m')}"
        )

    async def start_scheduler(self):
        """
        全局策略调度器 -- 在 startup 时调用
        
        只负责自动停止: 当用户的所有策略被停用时, 自动停止 autopilot。
        不会自动启动 autopilot -- 用户必须手动点击 Start。
        """
        logger.info("[Autopilot] Strategy scheduler started (auto-start DISABLED, manual only)")
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(Strategy).where(Strategy.is_active == True)
                    )
                    active = result.scalars().all()
                
                # 按 user_id 分组
                active_user_ids = set(s.user_id for s in active)
                
                # 只做自动停止: 停止没有活跃策略的用户
                for uid in list(self._tasks.keys()):
                    if uid not in active_user_ids:
                        await self.stop(uid, manual=False)
                        logger.info(f"[Autopilot] Auto-stopped for user {uid} (no active strategies)")
                
            except Exception as e:
                logger.error(f"[Autopilot] Scheduler error: {e}")
            
            await asyncio.sleep(30)

    async def stop(self, user_id: int, manual: bool = True):
        """停止自动决策"""
        task = self._tasks.pop(user_id, None)
        self._configs.pop(user_id, None)
        self._stats.pop(user_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if manual:
            self._manually_stopped.add(user_id)
            logger.info(f"[Autopilot] Manually stopped for user {user_id} (scheduler will NOT auto-restart)")
        else:
            logger.info(f"[Autopilot] Auto-stopped for user {user_id}")

    async def run_once(self, user_id: int, symbol: str = "BTCUSDT", strategy_id: int = None) -> str:
        """手动触发一次决策"""
        return await self._run_cycle(user_id, symbol, strategy_id=strategy_id)

    def get_status(self, user_id: int) -> dict:
        """获取运行状态 (增强版)"""
        running = self.is_running(user_id)
        config = self._configs.get(user_id, {})
        stats = self._stats.get(user_id, {})
        return {
            "running": running,
            "symbols": config.get("symbols", []),
            "interval": config.get("interval", "15m"),
            "started_at": stats.get("started_at"),
            "total_cycles": stats.get("total_cycles", 0),
            "last_cycle_at": stats.get("last_cycle_at"),
            "actions_taken": stats.get("actions_taken", 0),
        }

    async def get_logs(
        self,
        user_id: int,
        limit: int = 50,
        symbol: Optional[str] = None,
        since: Optional[str] = None,
    ) -> List[dict]:
        """获取决策日志"""
        async with AsyncSessionLocal() as db:
            query = (
                select(AutopilotLog)
                .where(AutopilotLog.user_id == user_id)
            )
            if symbol:
                query = query.where(AutopilotLog.symbol == symbol)
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    # 如果数据库中的时间是 naive (无时区)，去掉时区信息
                    since_dt = since_dt.replace(tzinfo=None)
                    query = query.where(AutopilotLog.created_at >= since_dt)
                except (ValueError, TypeError):
                    pass
            query = query.order_by(AutopilotLog.created_at.desc()).limit(limit)

            result = await db.execute(query)
            logs = result.scalars().all()

            return [
                {
                    "id": log.id,
                    "symbol": log.symbol,
                    "decision": log.decision,
                    "thinking": log.thinking,
                    "summary": log.summary,
                    "market_snapshot": log.market_snapshot,
                    "action_taken": log.action_taken,
                    "order_id": log.order_id,
                    "strategy_id": log.strategy_id,
                    "strategy_name": log.strategy_name,
                    "source": log.source or "autopilot",
                    "error_message": log.error_message,
                    "created_at": log.created_at.isoformat() + "Z" if log.created_at else None,
                }
                for log in logs
            ]

    # ============================================================
    # 内部方法
    # ============================================================

    async def _loop(self, user_id: int, config: dict):
        """定时循环"""
        interval = config.get("interval", "15m")
        seconds = INTERVAL_SECONDS.get(interval, 900)
        symbols = config.get("symbols", ["BTCUSDT"])
        intervals = config.get("intervals", [interval])

        logger.info(
            f"[Autopilot] Loop started: user={user_id}, "
            f"interval={seconds}s, symbols={symbols}, indicator_intervals={intervals}"
        )

        cycle_count = 0
        try:
            while True:
                for symbol in symbols:
                    try:
                        await self._run_cycle(user_id, symbol, intervals)
                    except Exception as e:
                        logger.error(
                            f"[Autopilot] Cycle error: user={user_id}, "
                            f"symbol={symbol}, error={e}"
                        )
                cycle_count += 1

                # 每 10 个周期做一次数据一致性检查
                if cycle_count % 10 == 0:
                    await self._health_check(user_id)
                
                # 每 5 个周期触发策略反思 (AI 回顾表现并优化)
                if cycle_count % 5 == 0:
                    await self._strategy_reflection(user_id)

                await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            logger.info(f"[Autopilot] Loop cancelled for user {user_id}")

    async def _health_check(self, user_id: int):
        """定期数据一致性检查"""
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select, func
                from app.models.position import Position, PositionStatus
                from app.models.wallet import Wallet
                from app.models.strategy import TradeMemory

                # 1. 检查交易日志 vs 已平仓
                closed_count = await db.scalar(
                    select(func.count(Position.id)).where(
                        Position.user_id == user_id,
                        Position.status == PositionStatus.CLOSED,
                    )
                )
                journal_count = await db.scalar(
                    select(func.count(TradeMemory.id)).where(
                        TradeMemory.user_id == user_id,
                        TradeMemory.source != "system",
                    )
                )
                if closed_count != journal_count:
                    logger.warning(
                        f"[Autopilot] ⚠️ Data mismatch: "
                        f"{journal_count} journal entries vs {closed_count} closed positions"
                    )

                # 2. 检查是否有无止损的开仓
                r = await db.execute(
                    select(Position).where(
                        Position.user_id == user_id,
                        Position.status == PositionStatus.OPEN,
                        Position.stop_loss == None,
                    )
                )
                no_sl = r.scalars().all()
                if no_sl:
                    symbols = [p.symbol for p in no_sl]
                    logger.warning(
                        f"[Autopilot] ⚠️ Positions without stop-loss: {symbols}"
                    )

                logger.info(
                    f"[Autopilot] Health check OK: user={user_id}, "
                    f"journal={journal_count}, closed={closed_count}"
                )
        except Exception as e:
            logger.warning(f"[Autopilot] Health check failed: {e}")

    async def _strategy_reflection(self, user_id: int):
        """
        策略反思 — AI 主理人回顾近期表现并提出优化

        每 5 个周期触发一次，通过 Agent 对话引擎完成反思。
        """
        try:
            async with AsyncSessionLocal() as db:
                # 获取最近的决策日志
                recent_logs = await db.execute(
                    select(AutopilotLog).where(
                        AutopilotLog.user_id == user_id,
                    ).order_by(AutopilotLog.created_at.desc()).limit(10)
                )
                logs = recent_logs.scalars().all()
                if not logs:
                    return

                # 构建反思 prompt
                actions = [l for l in logs if l.action_taken]
                holds = [l for l in logs if not l.action_taken]

                reflection_prompt = (
                    "[策略反思] 请回顾最近的自动交易表现:\n\n"
                    f"最近 {len(logs)} 次决策: {len(actions)} 次执行, {len(holds)} 次观望\n"
                )

                # 添加最近交易摘要
                for log in logs[:5]:
                    reflection_prompt += f"  - {log.symbol} | {log.decision} | {log.summary}\n"

                reflection_prompt += (
                    "\n请:\n"
                    "1. 查询交易记忆分析最近的盈亏情况\n"
                    "2. 查看当前活跃策略配置\n"
                    "3. 如果发现策略参数需要调整 (如止损/止盈/指标阈值), "
                    "使用 update_strategy 工具修改 (系统会自动验证YAML+干跑确保能运行)\n"
                    "4. 给出一句话总结当前策略表现\n"
                    "\n⚠️ 修改策略时必须使用 [TOOL_CALL: update_strategy(strategy_id=ID)] "
                    "并在正文写 ```yaml 代码块。系统会自动验证, 无效配置不会被保存。\n"
                    "\n最后写出: 策略优化建议: [无需调整/已优化参数/建议暂停]"
                )

                # 获取 autopilot 会话
                conv_id = await self._get_or_create_conversation(db, user_id)

                from app.services.agent.tools import agent_source_var
                token = agent_source_var.set('autopilot_reflection')
                try:
                    reply = await chat_complete(
                        db=db,
                        user_id=user_id,
                        conversation_id=conv_id,
                        user_message=reflection_prompt,
                        persona="autopilot",
                    )
                finally:
                    agent_source_var.reset(token)

                logger.info(
                    f"[Autopilot] Strategy reflection done for user {user_id}, "
                    f"reply_len={len(reply)}"
                )

        except Exception as e:
            logger.warning(f"[Autopilot] Strategy reflection failed: {e}")

    async def _run_cycle(self, user_id: int, symbol: str, intervals: list = None, strategy_id: int = None) -> str:
        """
        单次决策周期 (增强版)

        1. 获取/创建 autopilot 专属会话
        2. 预取技术指标
        3. 构造分析指令 (含指标数据)
        4. 调用 agent chat_complete (非流式)
        5. 解析 AI 回复 → 结构化日志
        6. 写入 AutopilotLog
        """
        if intervals is None:
            intervals = ["1h"]

        async with AsyncSessionLocal() as db:
            try:
                # 获取或创建 autopilot 会话
                conv_id = await self._get_or_create_conversation(db, user_id)

                # 预取技术指标 (使用用户选择的多个 K 线级别)
                indicator_text = await self._fetch_indicators(symbol, intervals)

                # 预取策略信号 (双路径: Pipeline 策略 vs 传统策略)
                strategy_text = ""
                pipeline_executed = False  # Pipeline 策略是否已直接执行
                try:
                    from app.services.quant.strategy import StrategyEngine
                    from app.core.network import net_manager
                    from sqlalchemy import select as _select

                    engine = StrategyEngine()
                    if strategy_id:
                        # run-once: only evaluate the specified strategy
                        strat_result = await db.execute(
                            _select(Strategy).where(
                                Strategy.id == strategy_id,
                                Strategy.user_id == user_id,
                            )
                        )
                    else:
                        strat_result = await db.execute(
                            _select(Strategy).where(
                                Strategy.user_id == user_id,
                                Strategy.is_active == True,
                            )
                        )
                    active_strategies = strat_result.scalars().all()

                    if active_strategies:
                        # 获取 K 线用于策略评估 — 使用策略定义的周期
                        strat_interval = active_strategies[0].interval if active_strategies else "1h"
                        klines = []
                        async with net_manager.get_client(timeout=15.0) as client:
                            resp = await client.get(
                                "https://fapi.binance.com/fapi/v1/klines",
                                params={"symbol": symbol, "interval": strat_interval, "limit": 200},
                            )
                            if resp.status_code == 200:
                                raw = resp.json()
                                klines = [{
                                    "open_time": k[0],
                                    "open": float(k[1]),
                                    "high": float(k[2]),
                                    "low": float(k[3]),
                                    "close": float(k[4]),
                                    "volume": float(k[5]),
                                    "close_time": k[6],
                                    "quote_volume": float(k[7]),
                                } for k in raw]

                        # 获取余额和持仓 (Pipeline 需要)
                        from app.services.wallet.manager import WalletManager
                        from app.models.position import Position, PositionStatus
                        from decimal import Decimal as _D

                        wallet = await WalletManager.get_wallet(db, user_id)
                        available_balance = wallet.balance - wallet.frozen if wallet else _D("0")
                        total_equity = wallet.balance if wallet else _D("0")

                        pos_result = await db.execute(
                            _select(Position).where(
                                Position.user_id == user_id,
                                Position.status == PositionStatus.OPEN,
                            )
                        )
                        open_positions = [
                            {"symbol": p.symbol, "side": p.side.value, "size": float(p.size)}
                            for p in pos_result.scalars().all()
                        ]

                        current_price = _D(str(klines[-1]["close"])) if klines else _D("0")

                        signals = []
                        pipeline_results = []

                        for strat in active_strategies:
                            try:
                                config = engine.parse_yaml(strat.config_yaml)
                                config["symbol"] = symbol

                                # Pipeline 策略检测: 包含 alphas 字段
                                is_pipeline = "alphas" in config

                                if is_pipeline and klines:
                                    # === Pipeline 路径: 直接走四步 ===
                                    from app.services.quant.pipeline_builder import build_pipeline_from_yaml
                                    pipeline = build_pipeline_from_yaml(config, user_id)

                                    results = await pipeline.process(
                                        symbol=symbol,
                                        price=current_price,
                                        db=db,
                                        available_balance=available_balance,
                                        total_equity=total_equity,
                                        open_positions=open_positions,
                                        klines=klines,
                                    )

                                    if results:
                                        for r in results:
                                            status = "✅ 已执行" if r.get("success") else f"❌ {r.get('error', '失败')}"
                                            signals.append(
                                                f"  - [Pipeline] {strat.name}: {status}"
                                                f" (order_id={r.get('order_id', 'N/A')})"
                                            )
                                            pipeline_results.append(r)
                                        pipeline_executed = True
                                    else:
                                        signals.append(
                                            f"  - [Pipeline] {strat.name}: 无信号 (Alpha 未触发)"
                                        )
                                else:
                                    # === 传统路径: 只评估信号，交给 AI 决策 ===
                                    if klines:
                                        signal = engine.evaluate(config, klines)
                                        signals.append(
                                            f"  - {strat.name}: {signal.summary()}"
                                        )
                            except Exception as se:
                                signals.append(
                                    f"  - {strat.name}: 评估异常 ({se})"
                                )

                        if signals:
                            strategy_text = (
                                "\n量化策略信号:\n"
                                + "\n".join(signals)
                            )

                        # 策略摘要注入 (仅名称+核心参数+信号, 禁止全文 YAML)
                        if active_strategies:
                            strategy_summaries = []
                            for strat in active_strategies:
                                # 提取核心参数摘要
                                try:
                                    config = engine.parse_yaml(strat.config_yaml)
                                    params = []
                                    if config.get("entry"):
                                        entry = config["entry"]
                                        if entry.get("rsi_below"): params.append(f"RSI<{entry['rsi_below']}")
                                        if entry.get("rsi_above"): params.append(f"RSI>{entry['rsi_above']}")
                                        if entry.get("macd_cross"): params.append(f"MACD={entry['macd_cross']}")
                                    if config.get("risk"):
                                        risk = config["risk"]
                                        if risk.get("stop_loss_pct"): params.append(f"SL={risk['stop_loss_pct']}%")
                                        if risk.get("take_profit_pct"): params.append(f"TP={risk['take_profit_pct']}%")
                                        if risk.get("max_position_pct"): params.append(f"MaxPos={risk['max_position_pct']}%")
                                    if config.get("alphas"):
                                        params.append(f"Pipeline({len(config['alphas'])} alphas)")
                                    param_str = ", ".join(params[:6]) if params else "custom"
                                except Exception:
                                    param_str = "parse error"
                                
                                signal_str = strat.last_signal or "N/A"
                                strategy_summaries.append(
                                    f"  - {strat.name} (ID={strat.id}, {strat.interval}): "
                                    f"[{param_str}] signal={signal_str}"
                                )
                            strategy_text += (
                                "\n\n激活策略概要:\n"
                                + "\n".join(strategy_summaries)
                            )
                except Exception as e:
                    logger.warning(f"[Autopilot] Strategy evaluation failed: {e}")

                # 预取交易记忆 (最近 5 条，供 AI 参考)
                memory_text = ""
                try:
                    from app.models.strategy import TradeMemory
                    mem_result = await db.execute(
                        select(TradeMemory).where(
                            TradeMemory.user_id == user_id,
                            TradeMemory.symbol == symbol,
                        ).order_by(TradeMemory.created_at.desc()).limit(5)
                    )
                    memories = mem_result.scalars().all()
                    if memories:
                        mem_lines = []
                        for m in memories:
                            pnl_str = f"+{m.realized_pnl}" if m.realized_pnl and m.realized_pnl > 0 else str(m.realized_pnl or 0)
                            mem_lines.append(f"  - {m.side} {m.symbol} | PnL: {pnl_str} | {m.lesson or ''}")
                        memory_text = "\n交易记忆 (最近):\n" + "\n".join(mem_lines)
                except Exception as e:
                    logger.debug(f"[Autopilot] Memory fetch failed: {e}")

                # 预取趋势分析结果
                trend_text = ""
                try:
                    from app.models.trend_scheme import TrendScheme
                    from app.services.quant.trend_analyzer import TrendAnalyzer, TrendResult
                    trend_result = await db.execute(
                        select(TrendScheme).where(
                            TrendScheme.user_id == user_id,
                            TrendScheme.is_active == True,
                        ).limit(1)
                    )
                    active_scheme = trend_result.scalar_one_or_none()
                    if active_scheme and active_scheme.last_result:
                        r = active_scheme.last_result
                        trend_text = (
                            f"\n🔍 趋势分析 ({active_scheme.name}):\n"
                            f"  方向: {r.get('direction', '?')} (分数: {r.get('direction_score', 0)})\n"
                            f"  强度: {r.get('strength', '?')} | 波动率: {r.get('volatility', '?')}\n"
                            f"  动量: {r.get('momentum', '?')} | 体制: {r.get('regime', '?')}\n"
                            f"  适合策略: {', '.join(r.get('suitable_strategies', []))}\n"
                            f"  不适合策略: {', '.join(r.get('unsuitable_strategies', []))}"
                        )
                except Exception as e:
                    logger.debug(f"[Autopilot] Trend fetch failed: {e}")

                # 预取资金费率
                funding_text = ""
                try:
                    from app.services.funding_rate import FundingRateService
                    rate_info = FundingRateService.get_cached_rate(symbol)
                    if rate_info:
                        rate = float(rate_info.get("lastFundingRate", 0))
                        rate_pct = rate * 100
                        annual_pct = rate * 3 * 365 * 100
                        direction = "多头付费" if rate > 0 else "空头付费" if rate < 0 else "零费率"
                        next_ts = rate_info.get("nextFundingTime", 0)
                        if next_ts:
                            remaining_min = max(0, (next_ts - int(utc_now().timestamp() * 1000)) // 60000)
                            time_str = f"{remaining_min // 60}h{remaining_min % 60}m后"
                        else:
                            time_str = "未知"
                        funding_text = (
                            f"\n💰 资金费率:\n"
                            f"  {symbol}: 当前 {rate_pct:.4f}% | 年化 {annual_pct:.2f}% | {direction}\n"
                            f"  标记价: {rate_info.get('markPrice', '?')} | 下次结算: {time_str}\n"
                            f"  (正费率=持多头需付费, 负费率=持空头需付费)"
                        )
                except Exception as e:
                    logger.debug(f"[Autopilot] Funding rate fetch failed: {e}")

                # 预取上次分析结论 (Scratchpad — AI 跨周期记忆)
                scratchpad_text = ""
                scratchpad_obj = None
                try:
                    from app.models.scratchpad import AnalysisScratchpad
                    sp_result = await db.execute(
                        select(AnalysisScratchpad).where(
                            AnalysisScratchpad.user_id == user_id,
                            AnalysisScratchpad.symbol == symbol,
                            AnalysisScratchpad.source == "autopilot",
                        ).limit(1)
                    )
                    scratchpad_obj = sp_result.scalar_one_or_none()
                    if scratchpad_obj and scratchpad_obj.context:
                        scratchpad_text = (
                            f"\n\U0001f4dd 上次分析结论 (你自己上次写的, 第{scratchpad_obj.cycle_count}次):\n"
                            f"{scratchpad_obj.context}\n"
                        )
                        if scratchpad_obj.key_levels:
                            scratchpad_text += f"关键价位: {json.dumps(scratchpad_obj.key_levels, ensure_ascii=False)}\n"
                        if scratchpad_obj.pattern_tracking:
                            scratchpad_text += f"形态追踪: {json.dumps(scratchpad_obj.pattern_tracking, ensure_ascii=False)}\n"
                except Exception as e:
                    logger.debug(f"[Autopilot] Scratchpad fetch failed: {e}")

                # 构造分析指令 (直接注入指标数据 + 策略信号 + 交易记忆 + 趋势分析 + 资金费率)
                now = utc_now().strftime("%Y-%m-%d %H:%M UTC")
                prompt = (
                    f"[Autopilot {now}] {symbol} 决策周期\n\n"
                    f"=== 市场数据 ===\n{indicator_text}\n"
                    f"{strategy_text}\n{trend_text}\n{funding_text}\n{memory_text}\n{scratchpad_text}\n\n"
                    f"=== 你的任务 ===\n"
                    f"你是量化分析师，基于上述数据做出交易决策。\n"
                    f"你只负责分析与决策，系统会自动执行你的信号。\n\n"
                    f"决策规则:\n"
                    f"1. 结合策略信号+趋势+指标+记忆综合判断\n"
                    f"2. 有明确做多/做空信号时，输出交易信号\n"
                    f"3. 已有持仓时，判断是否平仓\n"
                    f"4. 信号不明确才观望，不要永远观望\n"
                    f"5. 建议仓位不超过余额30%，必须有止损\n\n"
                    f"回复格式 (≤200字):\n"
                    f"**分析**: 一句话总结行情\n"
                    f"**决策**: 做多/做空/观望/平仓 (理由)\n"
                    f"**信号**: 如果不是观望，必须输出信号块:\n"
                    f"[TRADE_SIGNAL]\n"
                    f"direction=long 或 short 或 close\n"
                    f"confidence=0.0~1.0\n"
                    f"leverage=杠杆倍数\n"
                    f"sl_pct=止损百分比\n"
                    f"tp_pct=止盈百分比\n"
                    f"reason=一句话理由\n"
                    f"[/TRADE_SIGNAL]\n"
                    f"[SCRATCHPAD]你的分析记录[/SCRATCHPAD]"
                )

                # 调用 Agent (非流式) — 设置来源上下文
                from app.services.agent.tools import agent_source_var
                token = agent_source_var.set('autopilot')
                try:
                    reply = await chat_complete(
                        db=db,
                        user_id=user_id,
                        conversation_id=conv_id,
                        user_message=prompt,
                        persona="autopilot",
                    )
                finally:
                    agent_source_var.reset(token)

                # === 解析 AI 回复 → 结构化日志 ===
                decision = parse_decision(reply)
                summary = extract_summary(reply)
                action_taken = check_action_taken(reply)
                order_id = extract_order_id(reply) if action_taken else None

                # 写入 AutopilotLog (含策略关联)
                # 获取匹配的策略信息
                active_strategy_id = None
                active_strategy_name = None
                signal_data = None
                try:
                    if strategy_id:
                        # 指定了策略 ID，精确匹配
                        strat_q = await db.execute(
                            select(Strategy).where(
                                Strategy.id == strategy_id,
                                Strategy.user_id == user_id,
                            ).limit(1)
                        )
                    else:
                        # 未指定，匹配第一个活跃策略
                        strat_q = await db.execute(
                            select(Strategy).where(
                                Strategy.user_id == user_id,
                                Strategy.symbol == symbol,
                                Strategy.is_active == True,
                            ).limit(1)
                        )
                    matched_strat = strat_q.scalar_one_or_none()
                    if matched_strat:
                        active_strategy_id = matched_strat.id
                        active_strategy_name = matched_strat.name
                except Exception:
                    pass

                log = AutopilotLog(
                    user_id=user_id,
                    symbol=symbol,
                    decision=decision.value,
                    thinking=reply,
                    summary=summary,
                    action_taken=action_taken,
                    order_id=order_id,
                    strategy_id=active_strategy_id,
                    strategy_name=active_strategy_name,
                    source="autopilot",
                )
                db.add(log)

                # 更新策略的上次运行时间和信号
                if matched_strat:
                    matched_strat.last_run_at = utc_now()
                    matched_strat.last_signal = decision.value

                await db.commit()

                # 持久化 AI 的 Scratchpad
                try:
                    sp_match = re.search(
                        r'\[SCRATCHPAD\](.*?)\[/SCRATCHPAD\]',
                        reply, re.DOTALL,
                    )
                    if sp_match:
                        new_context = sp_match.group(1).strip()
                        if new_context:
                            from app.models.scratchpad import AnalysisScratchpad
                            if scratchpad_obj:
                                scratchpad_obj.context = new_context
                                scratchpad_obj.cycle_count += 1
                                scratchpad_obj.updated_at = utc_now()
                            else:
                                scratchpad_obj = AnalysisScratchpad(
                                    user_id=user_id,
                                    symbol=symbol,
                                    source="autopilot",
                                    context=new_context,
                                    cycle_count=1,
                                )
                                db.add(scratchpad_obj)
                            await db.commit()
                            logger.debug(
                                f"[Autopilot] Scratchpad saved for {symbol} "
                                f"(cycle #{scratchpad_obj.cycle_count})"
                            )
                except Exception as e:
                    logger.debug(f"[Autopilot] Scratchpad save failed: {e}")

                # ============================================================
                # 解析 AI 决策 → TradingSignal → ExternalSignalAlpha → Pipeline
                # ============================================================
                signal_emitted = False
                try:
                    sig_match = re.search(
                        r'\[TRADE_SIGNAL\](.*?)\[/TRADE_SIGNAL\]',
                        reply, re.DOTALL,
                    )
                    if sig_match and decision in (
                        AutopilotDecision.OPEN_LONG,
                        AutopilotDecision.OPEN_SHORT,
                        AutopilotDecision.CLOSE_LONG,
                        AutopilotDecision.CLOSE_SHORT,
                    ):
                        sig_text = sig_match.group(1).strip()
                        # 解析 key=value 对
                        sig_data = {}
                        for line in sig_text.split('\n'):
                            if '=' in line:
                                k, v = line.split('=', 1)
                                sig_data[k.strip().lower()] = v.strip()

                        direction = sig_data.get('direction', '')
                        if not direction:
                            # 从 decision 推断
                            if decision == AutopilotDecision.OPEN_LONG:
                                direction = 'long'
                            elif decision == AutopilotDecision.OPEN_SHORT:
                                direction = 'short'
                            elif decision in (AutopilotDecision.CLOSE_LONG, AutopilotDecision.CLOSE_SHORT):
                                direction = 'close'

                        confidence = float(sig_data.get('confidence', '0.6'))
                        leverage = int(float(sig_data.get('leverage', '3')))
                        sl_pct = float(sig_data.get('sl_pct', '2.0'))
                        tp_pct = float(sig_data.get('tp_pct', '6.0'))
                        reason = sig_data.get('reason', summary[:80])

                        from app.core.signal import TradingSignal
                        from app.core.event_bus import event_bus, Event, EventType

                        trading_signal = TradingSignal(
                            symbol=symbol,
                            direction=direction,
                            source="autopilot",
                            confidence=confidence,
                            reason=reason,
                            urgency="normal",
                            suggested_leverage=leverage,
                            suggested_sl_pct=sl_pct,
                            suggested_tp_pct=tp_pct,
                            metadata={
                                "strategy_id": active_strategy_id,
                                "strategy_name": active_strategy_name,
                                "decision": decision.value,
                            },
                        )

                        # 通过 EventBus 广播 (由 ExternalSignalAlpha 消费 → Pipeline 执行)
                        await event_bus.emit(Event(
                            type=EventType.EXTERNAL_SIGNAL,
                            data=trading_signal.to_dict(),
                            source="autopilot",
                            user_id=user_id,
                        ))

                        # 同时直接提交给 ExternalSignalAlpha
                        from app.services.alpha.external_signal import ExternalSignalAlpha
                        from app.core.pipeline import get_pipeline
                        pipeline = get_pipeline(user_id)
                        for alpha in pipeline._alphas:
                            if isinstance(alpha, ExternalSignalAlpha) and alpha._name == "autopilot":
                                await alpha.submit_signal(trading_signal)
                                break

                        signal_emitted = True
                        action_taken = True
                        logger.info(
                            f"[Autopilot] TradingSignal emitted: {symbol} "
                            f"{direction} conf={confidence:.0%} lev={leverage}x"
                        )

                except Exception as e:
                    logger.warning(f"[Autopilot] Signal emission failed: {e}")

                # 更新统计
                stats = self._stats.get(user_id)
                if stats:
                    stats["total_cycles"] = stats.get("total_cycles", 0) + 1
                    stats["last_cycle_at"] = now
                    if action_taken:
                        stats["actions_taken"] = stats.get("actions_taken", 0) + 1

                logger.info(
                    f"[Autopilot] Cycle done: user={user_id}, "
                    f"symbol={symbol}, decision={decision.value}, "
                    f"action={action_taken}, reply_len={len(reply)}"
                )
                return reply

            except Exception as e:
                await db.rollback()

                # 记录错误日志
                try:
                    error_log = AutopilotLog(
                        user_id=user_id,
                        symbol=symbol,
                        decision=AutopilotDecision.ERROR.value,
                        thinking=f"Error: {str(e)}",
                        summary=f"分析异常: {str(e)[:100]}",
                        error_message=str(e),
                        source="autopilot",
                    )
                    db.add(error_log)
                    await db.commit()
                except Exception:
                    pass

                logger.error(f"[Autopilot] run_cycle error: {e}")
                raise

    async def _fetch_indicators(self, symbol: str, intervals: list = None) -> str:
        """预取多级别技术指标，返回格式化文本注入 prompt"""
        if not intervals:
            intervals = ["1h"]

        # 确保所有 interval 格式正确
        interval_map = {
            "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "4h", "1d": "1d",
            "5分钟": "5m", "15分钟": "15m", "30分钟": "30m",
            "1小时": "1h", "4小时": "4h",
        }
        clean_intervals = [interval_map.get(i, i) for i in intervals]
        # 去重保序
        seen = set()
        unique_intervals = []
        for i in clean_intervals:
            if i not in seen:
                seen.add(i)
                unique_intervals.append(i)

        try:
            from app.core.network import net_manager
            results = {}

            async with net_manager.get_client(timeout=15.0) as client:
                import asyncio as aio
                tasks = {}
                for tf in unique_intervals:
                    tasks[tf] = client.get(
                        "https://fapi.binance.com/fapi/v1/klines",
                        params={"symbol": symbol.upper(), "interval": tf, "limit": 100},
                    )

                responses = await aio.gather(*tasks.values(), return_exceptions=True)

                for tf, resp in zip(tasks.keys(), responses):
                    if isinstance(resp, Exception):
                        logger.warning(f"[Autopilot] Klines {tf} error: {resp}")
                        continue
                    if resp.status_code != 200:
                        logger.warning(f"[Autopilot] Klines {tf} HTTP {resp.status_code}")
                        continue

                    raw = resp.json()
                    if not raw or len(raw) < 15:
                        continue

                    closes = [float(k[4]) for k in raw]

                    # RSI(14)
                    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                    gains = [c if c > 0 else 0 for c in changes[-14:]]
                    losses = [-c if c < 0 else 0 for c in changes[-14:]]
                    avg_gain = sum(gains) / 14
                    avg_loss = sum(losses) / 14
                    rsi = round(100 - (100 / (1 + avg_gain / avg_loss)), 2) if avg_loss > 0 else 100.0

                    ma7 = round(sum(closes[-7:]) / 7, 2)
                    ma25 = round(sum(closes[-25:]) / 25, 2) if len(closes) >= 25 else None

                    current = closes[-1]
                    trend = "neutral"
                    if ma7 and ma25:
                        if rsi > 50 and current > ma7 > ma25:
                            trend = "bullish"
                        elif rsi < 50 and current < ma7 < ma25:
                            trend = "bearish"

                    results[tf] = {"rsi": rsi, "ma7": ma7, "ma25": ma25, "trend": trend}

            if not results:
                return f"== 技术指标 ({symbol}) ==\n暂时无法获取，请使用工具 get_indicators 获取"

            # 格式化多级别输出
            trend_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}
            all_lines = [f"== 多级别技术指标 ({symbol}) =="]

            for tf in unique_intervals:
                if tf not in results:
                    continue
                d = results[tf]
                line = f"[{tf}] RSI:{d['rsi']}"
                if d['rsi'] > 70:
                    line += "(超买)"
                elif d['rsi'] < 30:
                    line += "(超卖)"
                line += f" | MA7:${d['ma7']:,.2f}"
                if d['ma25']:
                    line += f" | MA25:${d['ma25']:,.2f}"
                line += f" | {trend_cn.get(d['trend'], '中性')}"
                all_lines.append(line)

            logger.info(f"[Autopilot] Multi-TF indicators: {json.dumps({k: v['rsi'] for k, v in results.items()})}")
            return "\n".join(all_lines)

        except Exception as e:
            logger.warning(f"[Autopilot] Failed to fetch indicators: {e}")
        return f"== 技术指标 ({symbol}) ==\n暂时无法获取，请使用工具 get_indicators 获取"

    async def _get_or_create_conversation(
        self, db: AsyncSession, user_id: int
    ) -> int:
        """获取或创建 autopilot 专属会话 (每次启动重建)"""
        # 删除旧的 autopilot 会话，避免历史消息污染
        result = await db.execute(
            select(ChatConversation).where(
                ChatConversation.user_id == user_id,
                ChatConversation.persona == "autopilot",
            )
        )
        old_convs = result.scalars().all()

        if old_convs:
            from app.models.agent import ChatMessage as CM
            for old_conv in old_convs:
                # 删除旧会话的消息
                await db.execute(
                    CM.__table__.delete().where(CM.conversation_id == old_conv.id)
                )
                await db.delete(old_conv)
            await db.flush()
            logger.info(f"[Autopilot] Cleared {len(old_convs)} old conversation(s) for user {user_id}")

        conv = ChatConversation(
            user_id=user_id,
            persona="autopilot",
            title=f"{AUTOPILOT_TITLE_PREFIX} 自动交易记录",
        )
        db.add(conv)
        await db.flush()
        logger.info(
            f"[Autopilot] Created fresh conversation {conv.id} for user {user_id}"
        )
        return conv.id


# 全局单例
autopilot = AgentAutopilot()
