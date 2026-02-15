"""
Strategy Models
================
策略配置 + 执行日志 + 交易记忆

表:
- strategies: 策略配置 (YAML + 运行状态)
- strategy_logs: 策略执行日志
- trade_memories: AI 交易反思记忆库
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, Boolean, DateTime,
    ForeignKey, Index, Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Strategy(Base):
    """
    策略配置
    
    存储用户定义的 YAML 策略配置和运行状态
    """
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    
    name: Mapped[str] = mapped_column(
        String(100),
        comment="策略名称",
    )
    symbol: Mapped[str] = mapped_column(
        String(20),
        index=True,
        comment="交易对 (如 BTCUSDT)",
    )
    interval: Mapped[str] = mapped_column(
        String(10),
        default="1h",
        comment="K 线周期 (1m/5m/15m/1h/4h/1d)",
    )
    config_yaml: Mapped[str] = mapped_column(
        Text,
        comment="YAML 策略配置内容",
    )
    
    # 运行状态
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否正在自动运行",
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="上次执行时间",
    )
    last_signal: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="上次信号类型 (entry/exit/none)",
    )
    
    # 统计
    total_trades: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="总交易次数",
    )
    win_trades: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="盈利次数",
    )
    total_pnl: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="累计盈亏 (USDT)",
    )

    # 时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_strategies_user_active", "user_id", "is_active"),
    )

    def __repr__(self):
        status = "🟢" if self.is_active else "⚪"
        return f"<Strategy {status} {self.name} ({self.symbol})>"


class StrategyLog(Base):
    """
    策略执行日志
    
    记录每次策略评估周期的结果
    """
    __tablename__ = "strategy_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("strategies.id"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    # 信号信息
    signal_type: Mapped[str] = mapped_column(
        String(20),
        comment="信号类型: entry/exit/none",
    )
    action: Mapped[str] = mapped_column(
        String(20),
        comment="实际动作: executed/rejected_ai/rejected_risk/no_signal",
    )
    side: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="方向: buy/sell",
    )
    
    # AI 审核
    ai_approve: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="AI 是否批准",
    )
    ai_confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="AI 置信度 0-1",
    )
    ai_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI 审核理由",
    )
    
    # 风控
    risk_passed: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        comment="风控是否通过",
    )
    risk_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="风控拦截原因",
    )
    
    # 交易结果
    order_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="关联的订单 ID",
    )
    pnl: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="盈亏 (USDT)",
    )

    # 条件快照
    conditions_snapshot: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="条件评估快照 (JSON)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_strategy_logs_created", "strategy_id", "created_at"),
    )


class TradeMemory(Base):
    """
    交易反思记忆库
    
    AI 从每笔交易中总结的经验教训
    下次决策时自动注入给 AI 审核员参考
    """
    __tablename__ = "trade_memories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    
    symbol: Mapped[str] = mapped_column(
        String(20),
        index=True,
        comment="交易对",
    )
    strategy_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="策略名称",
    )
    
    # 交易结果
    trade_result: Mapped[str] = mapped_column(
        String(10),
        comment="win / loss",
    )
    pnl_pct: Mapped[float] = mapped_column(
        Float,
        comment="盈亏百分比",
    )
    
    # 反思内容  
    situation: Mapped[str] = mapped_column(
        Text,
        comment="当时的市场环境摘要",
    )
    lesson: Mapped[str] = mapped_column(
        Text,
        comment="经验教训 (核心记忆)",
    )
    what_went_right: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    what_went_wrong: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_trade_memories_symbol", "user_id", "symbol"),
    )

    def __repr__(self):
        emoji = "✅" if self.trade_result == "win" else "❌"
        return f"<TradeMemory {emoji} {self.symbol} {self.pnl_pct:+.1f}%>"
