"""
Position Model
===============
合约仓位数据模型

仓位代表用户在某个交易对上的持仓情况，
包含方向（多/空）、数量、开仓价格、杠杆、保证金等信息。
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import (
    String, 
    Integer, 
    Numeric, 
    Boolean, 
    DateTime, 
    ForeignKey,
    Enum as SQLEnum,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class PositionSide(str, Enum):
    """仓位方向"""
    LONG = "long"    # 做多
    SHORT = "short"  # 做空


class PositionStatus(str, Enum):
    """仓位状态"""
    OPEN = "open"        # 持仓中
    CLOSED = "closed"    # 已平仓
    LIQUIDATED = "liquidated"  # 已强平


class MarginMode(str, Enum):
    """保证金模式"""
    CROSS = "cross"      # 全仓
    ISOLATED = "isolated"  # 逐仓


class Position(Base):
    """
    合约仓位模型
    
    核心字段:
    - symbol: 交易对 (如 BTCUSDT)
    - side: 方向 (long/short)
    - size: 持仓数量 (BTC)
    - entry_price: 开仓均价
    - leverage: 杠杆倍数
    - margin: 占用保证金
    
    计算字段:
    - unrealized_pnl: 未实现盈亏 (需要实时价格计算)
    - liquidation_price: 强平价格
    
    风控字段:
    - stop_loss: 止损价
    - take_profit: 止盈价
    """
    __tablename__ = "positions"
    
    # ============================================
    # 主键和外键
    # ============================================
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), 
        index=True,
        nullable=False,
    )
    
    # ============================================
    # 核心仓位信息
    # ============================================
    
    symbol: Mapped[str] = mapped_column(
        String(20), 
        index=True, 
        nullable=False,
        comment="交易对，如 BTCUSDT",
    )
    
    side: Mapped[PositionSide] = mapped_column(
        SQLEnum(PositionSide),
        nullable=False,
        comment="仓位方向: long=做多, short=做空",
    )
    
    status: Mapped[PositionStatus] = mapped_column(
        SQLEnum(PositionStatus),
        default=PositionStatus.OPEN,
        nullable=False,
        comment="仓位状态",
    )
    
    size: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=False,
        comment="持仓数量 (如 0.5 BTC)",
    )
    
    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=False,
        comment="开仓均价",
    )
    
    # ============================================
    # 杠杆和保证金
    # ============================================
    
    leverage: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="杠杆倍数 (1-125)",
    )
    
    margin: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=False,
        comment="占用保证金 (USDT)",
    )
    
    margin_mode: Mapped[MarginMode] = mapped_column(
        SQLEnum(MarginMode),
        default=MarginMode.CROSS,  # 🔥 改为全仓模式
        nullable=False,
        comment="保证金模式: isolated=逐仓, cross=全仓",
    )
    
    # ============================================
    # 风控参数
    # ============================================
    
    liquidation_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=True,
        comment="强平价格",
    )
    
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
    # 盈亏统计
    # ============================================
    
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        nullable=False,
        comment="已实现盈亏",
    )
    
    # ============================================
    # 时间戳
    # ============================================
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow,
        nullable=False,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False,
    )
    
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="平仓时间",
    )
    
    # ============================================
    # 约束
    # ============================================
    
    __table_args__ = (
        # 持仓数量必须为正
        CheckConstraint("size > 0", name="check_size_positive"),
        # 杠杆必须在 1-125 之间
        CheckConstraint("leverage >= 1 AND leverage <= 125", name="check_leverage_range"),
        # 保证金必须为正
        CheckConstraint("margin > 0", name="check_margin_positive"),
    )
    
    # ============================================
    # 关系
    # ============================================
    
    user = relationship("User", back_populates="positions")
    
    # ============================================
    # 计算属性
    # ============================================
    
    def calculate_unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        """
        计算未实现盈亏
        
        Args:
            mark_price: 当前标记价格
            
        Returns:
            未实现盈亏 (正=盈利, 负=亏损)
        """
        if self.side == PositionSide.LONG:
            # 做多: (标记价 - 开仓价) × 数量
            return (mark_price - self.entry_price) * self.size
        else:
            # 做空: (开仓价 - 标记价) × 数量
            return (self.entry_price - mark_price) * self.size
    
    def calculate_roe(self, mark_price: Decimal) -> Decimal:
        """
        计算收益率 (ROE)
        
        Args:
            mark_price: 当前标记价格
            
        Returns:
            收益率百分比
        """
        pnl = self.calculate_unrealized_pnl(mark_price)
        if self.margin == 0:
            return Decimal("0")
        return (pnl / self.margin) * 100
    
    @property
    def notional_value(self) -> Decimal:
        """
        名义价值 = 数量 × 开仓价
        """
        return self.size * self.entry_price
    
    def __repr__(self) -> str:
        return (
            f"<Position(id={self.id}, user={self.user_id}, "
            f"symbol={self.symbol}, side={self.side.value}, "
            f"size={self.size}, entry={self.entry_price}, "
            f"leverage={self.leverage}x)>"
        )
