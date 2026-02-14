"""
WalletTransaction Model
========================
资金流水记录模型

记录所有钱包变动:
- deposit: 充值
- withdraw: 提现
- freeze: 冻结保证金 (开仓)
- unfreeze: 解冻 (撤单)
- pnl: 平仓盈亏结算
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import String, Numeric, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TransactionType(str, Enum):
    """交易类型"""
    DEPOSIT = "deposit"           # 充值
    WITHDRAW = "withdraw"         # 提现
    FREEZE = "freeze"             # 冻结保证金
    UNFREEZE = "unfreeze"         # 解冻 (撤单)
    PNL = "pnl"                   # 盈亏结算
    FEE = "fee"                   # 手续费
    FUNDING = "funding"           # 资金费用
    RESET = "reset"               # 重置余额


class WalletTransaction(Base):
    """
    钱包流水记录
    
    记录每一笔资金变动，用于:
    1. 资金对账
    2. 用户查看流水
    3. 审计追溯
    """
    
    __tablename__ = "wallet_transactions"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # 用户 ID
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # 交易类型
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    
    # 金额 (正=增加, 负=减少)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=False,
    )
    
    # 交易后余额
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8),
        nullable=False,
    )
    
    # 关联订单/仓位 ID (可选)
    related_order_id: Mapped[int] = mapped_column(nullable=True)
    related_position_id: Mapped[int] = mapped_column(nullable=True)
    
    # 备注
    note: Mapped[str] = mapped_column(Text, nullable=True)
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow,
        index=True,
    )
    
    # 索引优化
    __table_args__ = (
        Index('ix_wallet_tx_user_time', 'user_id', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<WalletTransaction(id={self.id}, user={self.user_id}, "
            f"type={self.type}, amount={self.amount})>"
        )
