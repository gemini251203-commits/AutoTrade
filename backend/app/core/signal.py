"""
Trading Signal — 外部信号的统一格式
====================================
任何外部 AI 模块 (推特监控/链上分析/新闻 AI 等)
都使用此格式将交易信号推入系统。

信号进入后会被 ExternalSignalAlpha 适配器转换为 Insight,
自动经过 Pipeline 的 Portfolio → Risk → Execution 层。

用法:
    from app.core.signal import TradingSignal

    signal = TradingSignal(
        symbol="BTCUSDT",
        direction="long",
        source="twitter_ai",
        confidence=0.85,
        reason="马斯克发推看涨 BTC",
    )
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from app.core.time_utils import utc_now


@dataclass
class TradingSignal:
    """
    外部交易信号 — 标准化的信号投递格式

    Attributes:
        symbol: 交易对, e.g. "BTCUSDT"
        direction: 方向 — "long" / "short" / "close" / "neutral"
        source: 信号来源标识, e.g. "twitter_ai" / "onchain_ai"
        confidence: 信心度 0.0 ~ 1.0 (影响仓位大小)
        reason: 人可读的理由 (会记入日志)
        urgency: 紧迫度 — "low" / "normal" / "high" / "critical"
        suggested_leverage: 建议杠杆, 0=让 Portfolio 决定
        suggested_sl_pct: 建议止损%, 0=用默认
        suggested_tp_pct: 建议止盈%, 0=用默认
        ttl_seconds: 信号有效期 (秒), 超时作废
        metadata: 来源专属数据 (推特ID/交易哈希等)
    """

    # === 必填 ===
    symbol: str
    direction: str                  # "long" / "short" / "close" / "neutral"
    source: str                     # 来源标识
    confidence: float               # 0.0 ~ 1.0

    # === 可选 ===
    reason: str = ""
    urgency: str = "normal"         # "low" / "normal" / "high" / "critical"
    suggested_leverage: int = 0
    suggested_sl_pct: float = 0.0
    suggested_tp_pct: float = 0.0
    ttl_seconds: int = 3600         # 默认 1 小时有效
    metadata: Dict[str, Any] = field(default_factory=dict)

    # === 自动填充 ===
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=lambda: utc_now())

    def __repr__(self) -> str:
        return (
            f"<Signal({self.signal_id} {self.symbol} {self.direction} "
            f"conf={self.confidence:.0%} src={self.source})>"
        )

    @property
    def is_actionable(self) -> bool:
        """是否可执行 (排除 neutral 和低信心)"""
        return self.direction in ("long", "short", "close") and self.confidence >= 0.3

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        from datetime import timedelta
        return utc_now() > self.timestamp + timedelta(seconds=self.ttl_seconds)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (用于 EventBus 广播)"""
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "source": self.source,
            "confidence": self.confidence,
            "reason": self.reason,
            "urgency": self.urgency,
            "suggested_leverage": self.suggested_leverage,
            "suggested_sl_pct": self.suggested_sl_pct,
            "suggested_tp_pct": self.suggested_tp_pct,
            "ttl_seconds": self.ttl_seconds,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }
