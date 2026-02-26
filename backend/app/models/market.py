"""
Market Data Models
==================
K 线 (Candlestick) 数据模型

用于存储从币安爬取的历史和实时行情数据。
支持多币种、多时间周期，前端 K 线图和回测系统统一数据源。
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, BigInteger, Numeric, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class Kline(Base):
    """
    K 线数据模型
    
    表结构:
    - symbol: 交易对 (如 "BTCUSDT")
    - interval: 时间周期 (如 "1m", "5m", "1h", "1d")
    - open_time: 开盘时间 (毫秒时间戳)
    - open/high/low/close: OHLC 价格
    - volume: 成交量
    
    索引:
    - symbol: 快速筛选币种
    - open_time: 快速排序
    - (symbol, interval, open_time): 唯一约束，防止重复
    """
    
    __tablename__ = "klines"
    
    # 主键
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # 交易对 (如 "BTCUSDT")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    
    # 时间周期 (如 "1m", "5m", "15m", "30m", "1h", "4h", "1d")
    interval: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    
    # 开盘时间 (毫秒时间戳，便于和币安 API 对接)
    open_time: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    
    # OHLC 价格 (使用 Numeric 确保精度)
    open: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    
    # 成交量
    volume: Mapped[Decimal] = mapped_column(Numeric(precision=20, scale=8), nullable=False)
    
    # 收盘时间 (可选)
    close_time: Mapped[int] = mapped_column(BigInteger, nullable=True)
    
    # 成交额 (可选)
    quote_volume: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), nullable=True
    )
    
    # 成交笔数 (可选)
    trades: Mapped[int] = mapped_column(BigInteger, nullable=True)
    
    # 创建/更新时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
    
    # 复合唯一约束: 同一币种、周期、时间只能有一条记录
    __table_args__ = (
        UniqueConstraint('symbol', 'interval', 'open_time', name='uq_kline_unique'),
        Index('ix_kline_symbol_interval_time', 'symbol', 'interval', 'open_time'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<Kline({self.symbol} {self.interval} "
            f"{self.open_time} O:{self.open} H:{self.high} L:{self.low} C:{self.close})>"
        )
