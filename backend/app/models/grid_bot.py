"""
GridBot Model
==============
网格交易机器人模型

网格交易策略:
- 在价格区间内设置多个买卖点
- 价格下跌时自动买入 (加仓)
- 价格上涨时自动卖出 (平仓)
- 通过高抛低吸赚取波动差价

网格类型:
- ARITHMETIC: 等差网格 (价格等距)
- GEOMETRIC: 等比网格 (百分比等距)

网格状态:
- CREATED: 已创建 (未启动)
- RUNNING: 运行中
- PAUSED: 已暂停
- STOPPED: 已停止
- COMPLETED: 已完成
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List

from sqlalchemy import String, Integer, Numeric, DateTime, Boolean, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GridType(str, Enum):
    """网格类型"""
    ARITHMETIC = "arithmetic"  # 等差网格
    GEOMETRIC = "geometric"    # 等比网格


class GridStatus(str, Enum):
    """网格状态"""
    CREATED = "created"      # 已创建
    RUNNING = "running"      # 运行中
    PAUSED = "paused"        # 已暂停
    STOPPED = "stopped"      # 已停止
    COMPLETED = "completed"  # 已完成


class GridDirection(str, Enum):
    """网格方向"""
    LONG = "long"    # 做多网格 (低买高卖)
    SHORT = "short"  # 做空网格 (高卖低买)
    NEUTRAL = "neutral"  # 中性网格 (双向)


class GridBot(Base):
    """
    网格交易机器人模型
    
    核心参数:
    - upper_price / lower_price: 网格上下边界
    - grid_count: 网格数量
    - investment: 投入金额
    - leverage: 杠杆倍数
    
    运行时数据:
    - current_level: 当前网格级别
    - filled_buy_count: 已成交买单数
    - filled_sell_count: 已成交卖单数
    - realized_pnl: 已实现盈亏
    """
    
    __tablename__ = "grid_bots"
    
    # ============================================
    # 主键和外键
    # ============================================
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), 
        index=True,
    )
    
    # ============================================
    # 基本配置
    # ============================================
    
    name: Mapped[str] = mapped_column(
        String(100),
        comment="机器人名称",
    )
    
    symbol: Mapped[str] = mapped_column(
        String(20), 
        index=True,
        comment="交易对，如 BTCUSDT",
    )
    
    grid_type: Mapped[GridType] = mapped_column(
        SQLEnum(GridType),
        default=GridType.ARITHMETIC,
        comment="网格类型: arithmetic=等差, geometric=等比",
    )
    
    direction: Mapped[GridDirection] = mapped_column(
        SQLEnum(GridDirection),
        default=GridDirection.LONG,
        comment="网格方向: long=做多, short=做空, neutral=中性",
    )
    
    status: Mapped[GridStatus] = mapped_column(
        SQLEnum(GridStatus),
        default=GridStatus.CREATED,
        comment="运行状态",
    )
    
    # ============================================
    # 网格参数
    # ============================================
    
    upper_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        comment="网格上边界价格",
    )
    
    lower_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        comment="网格下边界价格",
    )
    
    grid_count: Mapped[int] = mapped_column(
        Integer,
        comment="网格数量 (2-200)",
    )
    
    investment: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        comment="投入金额 (USDT)",
    )
    
    leverage: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="杠杆倍数 (1-125)",
    )
    
    # ============================================
    # 计算字段 (网格创建时计算)
    # ============================================
    
    grid_interval: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=True,
        comment="网格间距 (等差) 或 百分比 (等比)",
    )
    
    quantity_per_grid: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=True,
        comment="每格交易数量",
    )
    
    # ============================================
    # 止盈止损
    # ============================================
    
    stop_loss_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=True,
        comment="止损价格 (触发后停止机器人)",
    )
    
    take_profit_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=True,
        comment="止盈价格 (触发后停止机器人)",
    )
    
    # ============================================
    # 运行时统计
    # ============================================
    
    current_level: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="当前网格级别 (0 = 最底层)",
    )
    
    filled_buy_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="已成交买单数",
    )
    
    filled_sell_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="已成交卖单数",
    )
    
    total_profit: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        comment="累计网格利润",
    )
    
    total_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        comment="累计手续费",
    )
    
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        comment="已实现盈亏 (利润 - 手续费)",
    )
    
    # 累计资金费率费用 (正=支出, 负=收入)
    total_funding_fee: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        default=Decimal("0"),
        server_default="0",
        comment="累计资金费率费用",
    )
    
    # 网格级别详情 (JSON 存储)
    grid_levels: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="网格级别详情 [{price, buy_order_id, sell_order_id, status}, ...]",
    )
    
    # ============================================
    # 时间戳
    # ============================================
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="启动时间",
    )
    
    stopped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="停止时间",
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    
    # ============================================
    # 关联
    # ============================================
    
    user: Mapped["User"] = relationship("User")
    
    # ============================================
    # 计算属性
    # ============================================
    
    @property
    def is_active(self) -> bool:
        """是否活跃"""
        return self.status in (GridStatus.RUNNING, GridStatus.PAUSED)
    
    @property
    def profit_rate(self) -> Decimal:
        """收益率 (%)"""
        if self.investment == 0:
            return Decimal("0")
        return (self.realized_pnl / self.investment) * 100
    
    @property
    def matched_count(self) -> int:
        """成交配对数 (一买一卖为一对)"""
        return min(self.filled_buy_count, self.filled_sell_count)
    
    def __repr__(self) -> str:
        return (
            f"<GridBot(id={self.id}, name={self.name}, "
            f"symbol={self.symbol}, status={self.status.value})>"
        )
