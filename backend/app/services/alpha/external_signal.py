"""
External Signal Alpha — 外部信号适配器
=======================================
将外部 AI 模块的 TradingSignal 转换为 Insight, 注入 Pipeline

这是未来扩展新 AI 模块的唯一接入点:
- 推特监控 AI → submit_signal() → Pipeline
- 链上数据 AI → submit_signal() → Pipeline
- 新闻情绪 AI → submit_signal() → Pipeline

所有信号都会经过 Portfolio → Risk → Execution 层,
确保风控和仓位管理的一致性。

用法:
    from app.services.alpha.external_signal import ExternalSignalAlpha
    from app.core.signal import TradingSignal

    # 1. 创建适配器并注册到 Pipeline
    alpha = ExternalSignalAlpha(name="twitter_ai")
    pipeline.add_alpha(alpha)

    # 2. 任何地方推送信号
    await alpha.submit_signal(TradingSignal(
        symbol="BTCUSDT",
        direction="long",
        source="twitter_ai",
        confidence=0.8,
        reason="马斯克发推看涨 BTC",
    ))
"""

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional

from loguru import logger

from app.services.alpha.base import AlphaModel, Insight, InsightDirection, InsightStrength
from app.core.signal import TradingSignal
from app.core.event_bus import event_bus, Event, EventType


# TradingSignal direction → Insight direction 映射
_DIRECTION_MAP = {
    "long":    InsightDirection.UP,
    "short":   InsightDirection.DOWN,
    "neutral": InsightDirection.FLAT,
    "close":   InsightDirection.FLAT,
}

# urgency → InsightStrength 映射
_STRENGTH_MAP = {
    "low":      InsightStrength.WEAK,
    "normal":   InsightStrength.NORMAL,
    "high":     InsightStrength.STRONG,
    "critical": InsightStrength.STRONG,
}


class ExternalSignalAlpha(AlphaModel):
    """
    外部信号适配器 — 桥接 TradingSignal 和 Pipeline

    工作原理:
    1. 外部模块调用 submit_signal() 推入信号队列
    2. Pipeline 定时调用 update() 消费队列中的信号
    3. 信号转换为 Insight 后经过 Portfolio → Risk → Execution
    """

    def __init__(self, name: str = "external"):
        super().__init__()
        self._name = name
        self._pending: asyncio.Queue[TradingSignal] = asyncio.Queue()
        self._processed_count: int = 0
        self._rejected_count: int = 0

    def get_name(self) -> str:
        return f"ext:{self._name}"

    async def submit_signal(self, signal: TradingSignal) -> bool:
        """
        外部模块调用此方法推送信号

        Returns:
            True: 信号已入队
            False: 信号被拒绝 (过期/不可执行)
        """
        # 预检
        if signal.is_expired:
            logger.warning(f"[{self.get_name()}] Signal expired, rejected: {signal}")
            self._rejected_count += 1
            return False

        if not signal.is_actionable:
            logger.info(f"[{self.get_name()}] Signal not actionable, skipped: {signal}")
            self._rejected_count += 1
            return False

        # 入队
        await self._pending.put(signal)
        logger.info(f"[{self.get_name()}] Signal queued: {signal}")

        # 通过 EventBus 广播 (供日志/监控/前端订阅)
        try:
            await event_bus.emit_fire_and_forget(Event(
                type=EventType.EXTERNAL_SIGNAL,
                data=signal.to_dict(),
                source=signal.source,
                user_id=None,
            ))
        except Exception as e:
            logger.debug(f"[{self.get_name()}] EventBus emit failed (non-critical): {e}")

        return True

    async def update(self, symbol: str, price: Decimal, **kwargs) -> List[Insight]:
        """
        Pipeline 调用 — 消费队列中匹配 symbol 的信号

        不匹配的信号会放回队列, 等待下次调用。
        """
        if self._pending.empty():
            return []

        insights: List[Insight] = []
        requeue: List[TradingSignal] = []

        # 取出所有待处理信号
        batch: List[TradingSignal] = []
        while not self._pending.empty():
            try:
                batch.append(self._pending.get_nowait())
            except asyncio.QueueEmpty:
                break

        for sig in batch:
            # 过期检查
            if sig.is_expired:
                logger.info(f"[{self.get_name()}] Expired signal discarded: {sig}")
                self._rejected_count += 1
                continue

            # Symbol 匹配
            if sig.symbol.upper() != symbol.upper():
                requeue.append(sig)
                continue

            # 转换
            insight = self._to_insight(sig)
            insights.append(insight)
            self._processed_count += 1
            logger.info(
                f"[{self.get_name()}] Signal → Insight: "
                f"{sig.signal_id} → {insight.summary()}"
            )

        # 不匹配的放回
        for sig in requeue:
            await self._pending.put(sig)

        return insights

    def _to_insight(self, sig: TradingSignal) -> Insight:
        """TradingSignal → Insight 转换"""
        return Insight(
            symbol=sig.symbol,
            direction=_DIRECTION_MAP.get(sig.direction, InsightDirection.FLAT),
            confidence=sig.confidence,
            source=f"ext:{sig.source}",
            period=timedelta(seconds=sig.ttl_seconds),
            strength=_STRENGTH_MAP.get(sig.urgency, InsightStrength.NORMAL),
            suggested_stop_loss_pct=sig.suggested_sl_pct or None,
            suggested_take_profit_pct=sig.suggested_tp_pct or None,
            suggested_leverage=sig.suggested_leverage or None,
            metadata={
                "signal_id": sig.signal_id,
                "reason": sig.reason,
                "urgency": sig.urgency,
                **sig.metadata,
            },
        )

    def get_stats(self) -> dict:
        """扩展统计信息"""
        base = super().get_stats()
        base.update({
            "pending_signals": self._pending.qsize(),
            "processed_count": self._processed_count,
            "rejected_count": self._rejected_count,
        })
        return base

    @property
    def pending_count(self) -> int:
        return self._pending.qsize()
