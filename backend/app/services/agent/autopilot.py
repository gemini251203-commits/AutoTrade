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
        intervals = config.get("intervals", [interval])

        logger.info(
            f"[Autopilot] Loop started: user={user_id}, "
            f"interval={seconds}s, symbols={symbols}, indicator_intervals={intervals}"
        )

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
                await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            logger.info(f"[Autopilot] Loop cancelled for user {user_id}")

    async def _run_cycle(self, user_id: int, symbol: str, intervals: list = None) -> str:
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
