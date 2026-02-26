"""
Task Ticket Model
==================
AI 任务单模型

指令流: User/AI -> Task Ticket (DB) -> Execution Engine -> Exchange
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from sqlalchemy import String, Numeric, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.time_utils import utc_now


class TaskSource(str, Enum):
    """任务来源"""
    USER = "user"       # 用户手动创建
    AI = "ai"           # AI 自动生成
    STRATEGY = "strategy"  # 策略触发


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"       # 待审批
    APPROVED = "approved"     # 已审批
    MONITORING = "monitoring" # 监控中 (右侧条件单)
    EXECUTING = "executing"   # 执行中
    COMPLETED = "completed"   # 已完成
    REJECTED = "rejected"     # 已拒绝
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消
    EXPIRED = "expired"       # 已超时


class TaskType(str, Enum):
    """任务类型"""
    BUY = "buy"           # 买入
    SELL = "sell"         # 卖出
    CLOSE = "close"       # 平仓
    ADJUST = "adjust"     # 调整仓位


class TradingMode(str, Enum):
    """交易模式"""
    LEFT_SIDE = "left_side"    # 左侧交易 (限价挂单)
    RIGHT_SIDE = "right_side"  # 右侧交易 (突破条件单)
    MARKET = "market"          # 即时市价单


class TradeSide(str, Enum):
    """交易方向"""
    LONG = "long"    # 做多
    SHORT = "short"  # 做空


class ConfirmInterval(str, Enum):
    """K线确认周期"""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"


class ConditionType(str, Enum):
    """
    条件单类型 (右侧交易)
    
    用于支持复杂的两阶段入场模式
    """
    # 简单突破: 价格突破触发价即入场
    SIMPLE_BREAKOUT = "simple_breakout"
    
    # 跌破回抽 (做多): 先跌破 trigger_price → 再回抽上 trigger_price
    # 场景: 当前价格高于阻力线，等待假突破回抽确认后做多
    BREAKDOWN_RECLAIM = "breakdown_reclaim"
    
    # 突破回撤 (做空): 先突破上 trigger_price → 再回撤下 trigger_price
    # 场景: 当前价格低于支撑线，等待假跌破反弹确认后做空
    BREAKOUT_PULLBACK = "breakout_pullback"


class TaskTicket(Base):
    """
    AI 任务单模型
    
    这是 AI 和执行引擎之间的"契约"。
    AI 生成任务单 -> 用户审批 -> 执行引擎执行
    """
    
    __tablename__ = "task_tickets"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    
    # 任务元信息
    source: Mapped[TaskSource] = mapped_column(SQLEnum(TaskSource))
    task_type: Mapped[TaskType] = mapped_column(SQLEnum(TaskType))
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus), default=TaskStatus.PENDING
    )
    
    # 左侧/右侧交易模式
    trading_mode: Mapped[TradingMode] = mapped_column(
        SQLEnum(TradingMode), default=TradingMode.MARKET, nullable=True
    )
    trade_side: Mapped[TradeSide] = mapped_column(
        SQLEnum(TradeSide), nullable=True
    )
    
    # 交易参数
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))  # buy/sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8))
    leverage: Mapped[int] = mapped_column(default=5, nullable=True)
    
    # 价格区间 (左侧交易: 入场价格)
    entry_low: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
    entry_high: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
    
    # 右侧交易: 条件单参数
    trigger_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )  # 突破触发价格
    max_deviation_pct: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=2), default=Decimal("0.5"), nullable=True
    )  # 最大偏离百分比
    confirm_interval: Mapped[ConfirmInterval] = mapped_column(
        SQLEnum(ConfirmInterval), default=ConfirmInterval.M15, nullable=True
    )  # K线确认周期
    confirm_count: Mapped[int] = mapped_column(
        default=1, nullable=True
    )  # 确认K线数量 (假突破防护)
    timeout_hours: Mapped[int] = mapped_column(
        default=24, nullable=True
    )  # 超时时间 (小时)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True
    )  # 过期时间
    
    # 🔥 两阶段条件单参数
    condition_type: Mapped[ConditionType] = mapped_column(
        SQLEnum(ConditionType), default=ConditionType.SIMPLE_BREAKOUT, nullable=True
    )  # 条件类型
    condition_phase: Mapped[int] = mapped_column(
        default=1, nullable=True
    )  # 当前阶段 (1=等待阶段1, 2=等待阶段2)
    phase1_triggered_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True
    )  # 阶段1触发时间
    
    # 止盈止损
    stop_loss: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
    take_profit: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
    
    # AI 分析数据
    ai_analysis: Mapped[dict] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(5, 2), nullable=True)
    
    # 执行结果
    execution_result: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    # 备注
    note: Mapped[str] = mapped_column(Text, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    # 关联
    user: Mapped["User"] = relationship("User", back_populates="tasks")
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="task")
    
    def __repr__(self) -> str:
        return f"<TaskTicket(id={self.id}, symbol={self.symbol}, type={self.task_type}, status={self.status})>"
