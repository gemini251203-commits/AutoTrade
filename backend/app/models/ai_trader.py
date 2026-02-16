"""
AI Trader Models
=================
AI 自主交易机器人的数据模型

表:
- ai_trader_decisions: AI 决策记录 (含完整思维链)
- ai_trader_configs: AI Trader 用户配置
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, Boolean, JSON,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AITraderDecision(Base):
    """
    AI 决策记录

    每次 AI 分析市场并做出决策时，完整记录:
    - 市场快照 (价格/指标)
    - 账户快照 (余额/持仓)
    - AI 的完整思考过程 (reasoning)
    - 参考了哪些历史经验
    - 最终行动和结果
    """
    __tablename__ = "ai_trader_decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 交易对
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="交易对 (如 BTCUSDT)",
    )

    # 决策周期编号
    cycle_no: Mapped[int] = mapped_column(
        default=0,
        comment="第几个决策周期",
    )

    # 行动决策
    action: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="决策: hold/open_long/open_short/close/add_position",
    )

    # ========== 核心: AI 思维链 ==========
    reasoning: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="AI 的完整思考过程 (为什么做这个决策)",
    )

    # 信心度
    confidence: Mapped[float] = mapped_column(
        Float, default=0.0,
        comment="AI 对决策的信心 (0.0-1.0)",
    )

    # ========== 快照数据 ==========
    market_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="决策时的市场快照 (价格/指标/K线摘要)",
    )
    account_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="决策时的账户快照 (余额/持仓)",
    )
    experience_used: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="本次决策参考的历史经验",
    )

    # ========== 交易参数 ==========
    risk_params: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="计划的交易参数 (仓位%/杠杆/止损/止盈及原因)",
    )

    # ========== 执行结果 ==========
    executed: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="是否实际执行了交易",
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        comment="关联的订单 ID",
    )
    reject_reason: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True,
        comment="未执行的原因 (风控拒绝/信心不足等)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )

    __table_args__ = (
        Index("ix_ai_trader_decisions_user_time", "user_id", "created_at"),
        Index("ix_ai_trader_decisions_user_symbol", "user_id", "symbol"),
    )

    def __repr__(self):
        return (
            f"<AITraderDecision {self.id}: {self.symbol} "
            f"{self.action} conf={self.confidence:.0%}>"
        )


class AITraderConfig(Base):
    """
    AI Trader 用户配置

    每个用户一条配置，控制 AI Trader 的行为
    """
    __tablename__ = "ai_trader_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # 是否启用
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="是否启用 AI Trader",
    )

    # 监控的交易对 (JSON 数组)
    symbols: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        default=lambda: ["BTCUSDT", "ETHUSDT"],
        comment='监控的交易对列表 (如 ["BTCUSDT","ETHUSDT"])',
    )

    # 决策频率
    interval: Mapped[str] = mapped_column(
        String(10), default="15m",
        comment="决策频率: 5m/15m/30m/1h/4h",
    )

    # 风险参数
    max_position_pct: Mapped[float] = mapped_column(
        Float, default=30.0,
        comment="单笔最大仓位占比 (%)",
    )
    max_leverage: Mapped[int] = mapped_column(
        Integer, default=20,
        comment="最大杠杆倍数",
    )
    min_confidence: Mapped[float] = mapped_column(
        Float, default=0.6,
        comment="最低信心阈值 (低于此值不执行)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self):
        return (
            f"<AITraderConfig user={self.user_id} "
            f"enabled={self.enabled} intervals={self.interval}>"
        )
