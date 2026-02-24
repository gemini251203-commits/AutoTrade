"""
Autopilot Log Model
====================
自动交易决策日志

记录每次 autopilot 分析周期的:
- 市场快照 (价格/指标)
- AI 思考过程
- 决策结果
- 执行操作
"""

from datetime import datetime
from typing import Optional
from enum import Enum as PyEnum

from sqlalchemy import (
    String, Integer, Text, DateTime, Boolean,
    ForeignKey, Index, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutopilotDecision(str, PyEnum):
    """Autopilot 决策类型"""
    HOLD = "hold"              # 观望
    OPEN_LONG = "open_long"    # 开多
    OPEN_SHORT = "open_short"  # 开空
    CLOSE_LONG = "close_long"  # 平多
    CLOSE_SHORT = "close_short"  # 平空
    ERROR = "error"            # 异常


class AutopilotLog(Base):
    """
    Autopilot 决策日志

    每次 autopilot 分析周期生成一条记录，
    包含完整的思考过程、决策和操作结果。
    """
    __tablename__ = "autopilot_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    # 分析目标
    symbol: Mapped[str] = mapped_column(
        String(20),
        comment="交易对 (e.g. BTCUSDT)",
    )

    # 决策结果
    decision: Mapped[str] = mapped_column(
        String(20),
        default="hold",
        comment="决策: hold/open_long/open_short/close_long/close_short/error",
    )

    # AI 思考与摘要
    thinking: Mapped[str] = mapped_column(
        Text,
        default="",
        comment="AI 完整思考过程 (含工具调用结果)",
    )
    summary: Mapped[str] = mapped_column(
        String(200),
        default="",
        comment="一句话决策摘要",
    )

    # 市场快照
    market_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="市场数据快照 {price, change_24h, ...}",
    )

    # 执行记录
    action_taken: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否执行了交易操作",
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="关联的订单ID (如有操作)",
    )

    # 策略关联
    strategy_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="关联的策略ID (如有)",
    )
    strategy_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="策略名称",
    )

    # 来源标识
    source: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        default="autopilot",
        comment="来源: autopilot/agent/news/quant",
    )

    signal_raw: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="策略评估原始信号 {signal_type, conditions, ...}",
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息 (如有)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_autopilot_logs_user_time", "user_id", "created_at"),
        Index("ix_autopilot_logs_user_symbol", "user_id", "symbol"),
    )

    def __repr__(self):
        return f"<AutopilotLog {self.symbol} {self.decision} @ {self.created_at}>"
