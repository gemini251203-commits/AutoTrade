"""
Order Model
============
交易订单模型 (合约交易版)

订单类型:
- market: 市价单 (立即以当前价格成交)
- limit: 限价单 (挂单等待价格触发)
- stop_market: 止损市价单 (触发后以市价成交)
- stop_limit: 止损限价单 (触发后以限价挂单)
- take_profit_market: 止盈市价单
- take_profit_limit: 止盈限价单

订单生命周期:
PENDING → OPEN → (PARTIAL) → FILLED / CANCELLED / FAILED
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import String, Integer, Numeric, DateTime, Boolean, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"    # 买入/做多
    SELL = "sell"  # 卖出/做空


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"                       # 市价单
    LIMIT = "limit"                         # 限价单
    STOP_MARKET = "stop_market"             # 止损市价单
    STOP_LIMIT = "stop_limit"               # 止损限价单
    TAKE_PROFIT_MARKET = "take_profit_market"  # 止盈市价单
    TAKE_PROFIT_LIMIT = "take_profit_limit"    # 止盈限价单


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"       # 待执行 (条件单等待触发)
    OPEN = "open"             # 已挂单 (限价单等待成交)
    PARTIAL = "partial"       # 部分成交
    FILLED = "filled"         # 完全成交
    CANCELLED = "cancelled"   # 已取消
    FAILED = "failed"         # 失败
    EXPIRED = "expired"       # 已过期


class PositionSideEnum(str, Enum):
    """仓位方向 (用于区分开仓/平仓)"""
    LONG = "long"    # 做多
    SHORT = "short"  # 做空
    BOTH = "both"    # 双向持仓模式


class Order(Base):
    """
    交易订单模型 (合约交易版)
    
    新增字段:
    - leverage: 杠杆倍数
    - trigger_price: 触发价格 (条件单)
    - position_side: 仓位方向 (开多/开空/平多/平空)
    - reduce_only: 只减仓
    - close_position: 平掉全部仓位
    - avg_fill_price: 平均成交价
    - commission: 手续费
    - realized_pnl: 已实现盈亏
    """
    
    __tablename__ = "orders"
    
    # ============================================
    # 主键和外键
    # ============================================
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    
    # ============================================
    # 订单基本信息
    # ============================================
    
    symbol: Mapped[str] = mapped_column(
        String(20), 
        index=True,
        comment="交易对，如 BTCUSDT",
    )
    
    side: Mapped[OrderSide] = mapped_column(
        SQLEnum(OrderSide),
        comment="订单方向: buy=买入, sell=卖出",
    )
    
    order_type: Mapped[OrderType] = mapped_column(
        SQLEnum(OrderType),
        comment="订单类型",
    )
    
    status: Mapped[OrderStatus] = mapped_column(
        SQLEnum(OrderStatus), 
        default=OrderStatus.PENDING,
        comment="订单状态",
    )
    
    # ============================================
    # 杠杆和仓位
    # ============================================
    
    leverage: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="杠杆倍数 (1-125)",
    )
    
    position_side: Mapped[Optional[PositionSideEnum]] = mapped_column(
        SQLEnum(PositionSideEnum),
        nullable=True,
        comment="仓位方向: long=做多, short=做空",
    )
    
    reduce_only: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="只减仓 (不开新仓)",
    )
    
    close_position: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="平掉全部仓位",
    )
    
    # ============================================
    # 价格和数量
    # ============================================
    
    price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), 
        nullable=True,
        comment="限价单价格 (市价单可为空)",
    )
    
    trigger_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), 
        nullable=True,
        comment="触发价格 (条件单)",
    )
    
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        comment="订单数量",
    )
    
    filled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), 
        default=Decimal("0"),
        comment="已成交数量",
    )
    
    avg_fill_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=True,
        comment="平均成交价",
    )
    
    # ============================================
    # 止盈止损 (附加到仓位)
    # ============================================
    
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), 
        nullable=True,
        comment="止损价格",
    )
    
    take_profit: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8), 
        nullable=True,
        comment="止盈价格",
    )
    
    # ============================================
    # 费用和盈亏
    # ============================================
    
    commission: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        comment="手续费 (USDT)",
    )
    
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        comment="已实现盈亏",
    )
    
    # ============================================
    # 交易所和来源
    # ============================================
    
    exchange_order_id: Mapped[Optional[str]] = mapped_column(
        String(100), 
        nullable=True,
        comment="交易所订单 ID",
    )
    
    task_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("task_tickets.id"), 
        nullable=True,
        comment="来源任务 ID",
    )
    
    position_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("positions.id"),
        nullable=True,
        comment="关联仓位 ID",
    )
    
    note: Mapped[Optional[str]] = mapped_column(
        Text, 
        nullable=True,
        comment="备注",
    )
    
    # ============================================
    # 时间戳
    # ============================================
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
    )
    
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="成交时间",
    )
    
    expired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="过期时间 (可选)",
    )
    
    # ============================================
    # 关联
    # ============================================
    
    user: Mapped["User"] = relationship("User", back_populates="orders")
    task: Mapped["TaskTicket"] = relationship("TaskTicket", back_populates="orders")
    position: Mapped["Position"] = relationship("Position", foreign_keys=[position_id])
    
    # ============================================
    # 计算属性
    # ============================================
    
    @property
    def is_active(self) -> bool:
        """订单是否活跃 (可取消)"""
        return self.status in (
            OrderStatus.PENDING, 
            OrderStatus.OPEN, 
            OrderStatus.PARTIAL
        )
    
    @property
    def is_conditional(self) -> bool:
        """是否条件单"""
        return self.order_type in (
            OrderType.STOP_MARKET,
            OrderType.STOP_LIMIT,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.TAKE_PROFIT_LIMIT,
        )
    
    @property
    def fill_percentage(self) -> float:
        """成交百分比"""
        if self.quantity == 0:
            return 0.0
        return float(self.filled_quantity / self.quantity * 100)
    
    @property
    def remaining_quantity(self) -> Decimal:
        """剩余未成交数量"""
        return self.quantity - self.filled_quantity
    
    @property
    def notional_value(self) -> Decimal:
        """名义价值"""
        price = self.avg_fill_price or self.price or Decimal("0")
        return self.quantity * price
    
    def __repr__(self) -> str:
        return (
            f"<Order(id={self.id}, symbol={self.symbol}, "
            f"side={self.side.value}, type={self.order_type.value}, "
            f"status={self.status.value}, qty={self.quantity})>"
        )
