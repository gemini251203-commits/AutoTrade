"""
Exchange Adapter Base Class
============================
交易所适配器抽象基类

所有交易所（模拟盘、币安、OKX 等）都实现此接口，
使业务逻辑与具体交易所解耦。
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    TAKE_PROFIT_MARKET = "take_profit_market"


@dataclass
class OrderRequest:
    """订单请求"""
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None        # 限价单价格
    stop_price: Optional[Decimal] = None   # 触发价格
    leverage: int = 1
    reduce_only: bool = False


@dataclass
class OrderResult:
    """订单结果"""
    success: bool
    order_id: Optional[str] = None
    filled_price: Optional[Decimal] = None
    filled_quantity: Optional[Decimal] = None
    commission: Optional[Decimal] = None
    error_message: Optional[str] = None


@dataclass
class PositionInfo:
    """仓位信息"""
    symbol: str
    side: str  # long/short
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: int


class ExchangeAdapter(ABC):
    """
    交易所适配器抽象基类
    
    所有子类必须实现以下方法：
    - get_mark_price: 获取标记价格
    - place_order: 下单
    - cancel_order: 撤单
    - get_position: 获取仓位
    """
    
    @abstractmethod
    async def get_mark_price(self, symbol: str) -> Decimal:
        """
        获取标记价格
        
        Args:
            symbol: 交易对 (如 BTCUSDT)
            
        Returns:
            当前标记价格
        """
        pass
    
    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """
        下单
        
        Args:
            order: 订单请求
            
        Returns:
            订单结果
        """
        pass
    
    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        撤单
        
        Args:
            symbol: 交易对
            order_id: 订单 ID
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """
        获取仓位
        
        Args:
            symbol: 交易对
            
        Returns:
            仓位信息，无仓位时返回 None
        """
        pass
    
    @abstractmethod
    async def get_balance(self) -> Decimal:
        """
        获取账户余额
        
        Returns:
            USDT 余额
        """
        pass
