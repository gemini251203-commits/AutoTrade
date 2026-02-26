"""
Wallet Model (简化版)
======================
用户钱包模型 - 单用户单钱包设计

⚠️ 资金铁律 (ACID): 
所有余额变动必须在数据库事务中完成。
严禁出现"扣了钱没挂单"的情况。

字段说明:
- balance: 可用余额 (可以用来下单的钱)
- frozen: 冻结保证金 (已经下单锁定的钱)
- total_pnl: 已实现盈亏 (历史交易累计)

约束:
- balance >= 0 (不能透支)
- frozen >= 0 (冻结不能为负)
- 使用 Decimal/Numeric 类型确保精度 (严禁 float)
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Numeric, DateTime, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class Wallet(Base):
    """
    用户钱包模型
    
    ⚠️ 重要: 所有余额变动必须在数据库事务中完成
    
    表结构:
    - user_id: 用户唯一标识 (主键)
    - balance: 可用余额 (Decimal, 精度 20,8)
    - frozen: 冻结保证金 (Decimal, 精度 20,8)
    - total_pnl: 已实现盈亏 (Decimal, 精度 20,8)
    
    数据库约束:
    - balance >= 0
    - frozen >= 0
    """
    
    __tablename__ = "wallets"
    
    # 主键: 用户 ID (一个用户一个钱包)
    user_id: Mapped[int] = mapped_column(primary_key=True)
    
    # 可用余额 (使用 Numeric 确保精度, 严禁 float!)
    # precision=20: 总共 20 位数字
    # scale=8: 小数点后 8 位 (支持聪级别精度)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), 
        default=Decimal("0"),
        nullable=False
    )
    
    # 冻结保证金 (下单时从 balance 转入)
    frozen: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), 
        default=Decimal("0"),
        nullable=False
    )
    
    # 已实现盈亏 (历史交易累计, 可正可负)
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), 
        default=Decimal("0"),
        nullable=False
    )
    
    # 资金账户余额 (独立于合约账户, 不参与保证金计算)
    funding_balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=8), 
        default=Decimal("0"),
        nullable=False,
        server_default="0",
    )
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=utc_now, 
        onupdate=utc_now
    )
    
    # 数据库级别约束: 防止余额和冻结变为负数
    __table_args__ = (
        CheckConstraint('balance >= 0', name='check_balance_non_negative'),
        CheckConstraint('frozen >= 0', name='check_frozen_non_negative'),
        CheckConstraint('funding_balance >= 0', name='check_funding_non_negative'),
    )
    
    @property
    def total_equity(self) -> Decimal:
        """
        总权益 = 可用余额 + 冻结保证金
        
        这个值代表用户的总资产 (不包含未实现盈亏)
        """
        return self.balance + self.frozen
    
    @property
    def available_margin(self) -> Decimal:
        """
        可用保证金 = 可用余额
        
        这个值代表用户还能用来开仓的资金
        """
        return self.balance
    
    def __repr__(self) -> str:
        return (
            f"<Wallet(user_id={self.user_id}, "
            f"balance={self.balance}, "
            f"frozen={self.frozen}, "
            f"pnl={self.total_pnl})>"
        )
