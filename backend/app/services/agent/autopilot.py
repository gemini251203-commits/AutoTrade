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
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.session import AsyncSessionLocal
from app.models.agent import ChatConversation, ChatMessage
from app.models.autopilot_log import AutopilotLog, AutopilotDecision
from app.services.agent.agent import chat_complete


# 间隔映射 (秒)
INTERVAL_SECONDS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
}

# Autopilot 会话标识前缀
AUTOPILOT_TITLE_PREFIX = "[autopilot]"

# 决策关键词映射
DECISION_KEYWORDS = {
    AutopilotDecision.OPEN_LONG: [
        "开多", "做多", "买入开仓", "open_long", "open long", "buy",
        "看涨", "建仓做多",
    ],
    AutopilotDecision.OPEN_SHORT: [
        "开空", "做空", "卖出开仓", "open_short", "open short", "short",
        "看跌", "建仓做空",
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
    """从 AI 回复中解析决策类型"""
    text = ai_reply.lower()
    
    # 按优先级匹配 (操作 > 观望)
    for decision in [
        AutopilotDecision.OPEN_LONG,
        AutopilotDecision.OPEN_SHORT,
        AutopilotDecision.CLOSE_LONG,
        AutopilotDecision.CLOSE_SHORT,
    ]:
        for keyword in DECISION_KEYWORDS[decision]:
            if keyword.lower() in text:
                return decision
    
    # 检查是否调用了 place_order 工具 (说明有实际操作)
    if "place_order" in text:
        if "buy" in text or "做多" in text:
            return AutopilotDecision.OPEN_LONG
        elif "sell" in text or "做空" in text:
            return AutopilotDecision.OPEN_SHORT
    
    if "close_position" in text:
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
    """检查 AI 是否实际执行了交易操作"""
    action_keywords = [
        "place_order", "close_position", 
        "订单已创建", "下单成功", "开仓成功", "平仓成功",
        "order_id", "已执行",
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

        self._configs[user_id] = config
        self._stats[user_id] = {
            "started_at": datetime.utcnow().isoformat() + "Z",
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

    async def stop(self, user_id: int):
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
        logger.info(f"[Autopilot] Stopped for user {user_id}")

    async def run_once(self, user_id: int, symbol: str = "BTCUSDT") -> str:
        """手动触发一次决策"""
        return await self._run_cycle(user_id, symbol)

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
                    "error_message": log.error_message,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
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

        logger.info(
            f"[Autopilot] Loop started: user={user_id}, "
            f"interval={seconds}s, symbols={symbols}"
        )

        try:
            while True:
                for symbol in symbols:
                    try:
                        await self._run_cycle(user_id, symbol)
                    except Exception as e:
                        logger.error(
                            f"[Autopilot] Cycle error: user={user_id}, "
                            f"symbol={symbol}, error={e}"
                        )
                await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            logger.info(f"[Autopilot] Loop cancelled for user {user_id}")

    async def _run_cycle(self, user_id: int, symbol: str) -> str:
        """
        单次决策周期 (增强版)

        1. 获取/创建 autopilot 专属会话
        2. 预取技术指标
        3. 构造分析指令 (含指标数据)
        4. 调用 agent chat_complete (非流式)
        5. 解析 AI 回复 → 结构化日志
        6. 写入 AutopilotLog
        """
        async with AsyncSessionLocal() as db:
            try:
                # 获取或创建 autopilot 会话
                conv_id = await self._get_or_create_conversation(db, user_id)

                # 预取技术指标
                indicator_text = await self._fetch_indicators(symbol)

                # 构造分析指令 (直接注入指标数据)
                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                prompt = (
                    f"[Autopilot {now}] "
                    f"请分析 {symbol} 当前市场状况并做出交易决策。\n\n"
                    f"{indicator_text}\n\n"
                    f"请按以下步骤操作:\n"
                    f"1. 查询 {symbol} 实时价格 (如需更新)\n"
                    f"2. 查看当前持仓和余额\n"
                    f"3. 查询历史交易经验\n"
                    f"4. 结合上方技术指标综合分析后给出决策: 开仓/平仓/观望\n"
                    f"5. 如果决定交易, 直接执行\n\n"
                    f"回复要简洁, 列出关键数据和理由。\n"
                    f"最后一行请明确写出你的决策: 观望/开多/开空/平多/平空"
                )

                # 调用 Agent (非流式)
                reply = await chat_complete(
                    db=db,
                    user_id=user_id,
                    conversation_id=conv_id,
                    user_message=prompt,
                    persona="autopilot",
                )

                # === 解析 AI 回复 → 结构化日志 ===
                decision = parse_decision(reply)
                summary = extract_summary(reply)
                action_taken = check_action_taken(reply)
                order_id = extract_order_id(reply) if action_taken else None

                # 写入 AutopilotLog
                log = AutopilotLog(
                    user_id=user_id,
                    symbol=symbol,
                    decision=decision.value,
                    thinking=reply,
                    summary=summary,
                    action_taken=action_taken,
                    order_id=order_id,
                )
                db.add(log)
                await db.commit()

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
                    )
                    db.add(error_log)
                    await db.commit()
                except Exception:
                    pass

                logger.error(f"[Autopilot] run_cycle error: {e}")
                raise

    async def _fetch_indicators(self, symbol: str) -> str:
        """预取技术指标，返回格式化文本注入 prompt"""
        try:
            from app.core.network import net_manager
            async with net_manager.get_client(timeout=15.0) as client:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={"symbol": symbol.upper(), "interval": "1h", "limit": 100},
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    if raw and len(raw) >= 15:
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
                        trend_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}

                        logger.info(f"[Autopilot] Fetched indicators: RSI={rsi}, MA7={ma7}, MA25={ma25}, trend={trend}")
                        lines = [
                            f"== 技术指标 ({symbol}, 1h) ==",
                            f"RSI(14): {rsi}" + (" (超买)" if rsi > 70 else " (超卖)" if rsi < 30 else ""),
                            f"MA7: ${ma7:,.2f}",
                        ]
                        if ma25:
                            lines.append(f"MA25: ${ma25:,.2f}")
                        lines.append(f"趋势: {trend_cn.get(trend, '中性')}")
                        return "\n".join(lines)
                else:
                    logger.warning(f"[Autopilot] Binance klines HTTP {resp.status_code}")
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
        old_conv = result.scalar_one_or_none()

        if old_conv:
            # 删除旧会话的消息
            from app.models.agent import ChatMessage as CM
            await db.execute(
                CM.__table__.delete().where(CM.conversation_id == old_conv.id)
            )
            await db.delete(old_conv)
            await db.flush()
            logger.info(f"[Autopilot] Cleared old conversation {old_conv.id} for user {user_id}")

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
