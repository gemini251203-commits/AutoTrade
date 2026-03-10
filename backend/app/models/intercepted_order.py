"""
Intercepted Order Model (FOMO & Regret Log)
============================================
拦截订单记录表 — "死海古卷"

记录所有被风控拦截的交易意向，用于：
1. 复盘"踏空"场景 (本来该赚但被拦了)
2. 复盘"幸免于难"场景 (本来会亏但被拦了)
3. AI 策略审计 (哪个 Agent 被拦截最多)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Numeric, DateTime, Text,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class InterceptedOrder(Base):
    """
    拦截订单记录
    
    当风控拒绝一笔交易时，完整记录交易意向和拦截原因。
    后续可计算: 如果当时没拦，会赚还是会亏？
    """
    __tablename__ = "intercepted_orders"
    
    # === 主键 ===
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    
    # === 交易意向 ===
    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="交易对 (如 BTCUSDT)",
    )
    side: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="方向: buy/sell",
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0"),
        comment="意向数量",
    )
    leverage: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="意向杠杆",
    )
    price_at_intercept: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True,
        comment="拦截时的市场价格",
    )
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True,
        comment="意向止损价",
    )
    take_profit: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True,
        comment="意向止盈价",
    )
    
    # === 拦截信息 ===
    intercept_reason: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="拦截原因 (风控理由)",
    )
    intercept_source: Mapped[str] = mapped_column(
        String(30), default="risk_model",
        comment="拦截来源: risk_model/pipeline/agent_guard",
    )
    
    # === 来源追踪 ===
    source: Mapped[str] = mapped_column(
        String(20), default="unknown",
        comment="交易来源: agent/hub/autopilot/signal",
    )
    agent_name: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="提出交易的 Agent 名称",
    )
    
    # === 事后评估 (后续填充) ===
    price_after_1h: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True,
        comment="拦截后1小时价格 (事后回填)",
    )
    would_have_pnl: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 8), nullable=True,
        comment="假设未拦截的理论盈亏 (事后计算)",
    )
    verdict: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="事后裁定: dodged_bullet(幸免) / missed_opportunity(踏空) / neutral",
    )
    
    # === 时间戳 ===
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False,
    )
    
    # === 索引 ===
    __table_args__ = (
        Index("ix_intercepted_user_date", "user_id", "created_at"),
    )
    
    def __repr__(self) -> str:
        return (
            f"<InterceptedOrder {self.symbol} {self.side} "
            f"agent={self.agent_name} reason={self.intercept_reason[:30]}>"
        )
