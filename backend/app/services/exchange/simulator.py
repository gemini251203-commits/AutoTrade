"""
Simulator Exchange Adapter
===========================
模拟盘交易所适配器

使用币安实时价格，但订单在本地模拟执行：
- 市价单: 立即以标记价格成交
- 限价单: 挂单等待价格触发
- 条件单: 监控价格触发后执行
"""

from decimal import Decimal
from typing import Optional
from loguru import logger
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .base import (
    ExchangeAdapter, 
    OrderRequest, 
    OrderResult, 
    PositionInfo,
    OrderType,
)


class SimulatorAdapter(ExchangeAdapter):
    """
    模拟盘适配器
    
    特点:
    - 使用真实币安价格
    - 订单本地撮合
    - 适合策略测试
    """
    
    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory
    
    async def get_mark_price(self, symbol: str) -> Decimal:
        """
        获取标记价格
        
        从数据库读取最新 K 线收盘价作为标记价格
        """
        from app.models.market import Kline
        
        async with self.db_session_factory() as db:
            query = (
                select(Kline)
                .where(Kline.symbol == symbol)
                .where(Kline.interval == "1m")
                .order_by(desc(Kline.open_time))
                .limit(1)
            )
            result = await db.execute(query)
            kline = result.scalar_one_or_none()
            
            if kline:
                return Decimal(str(kline.close))
            else:
                logger.warning(f"[Simulator] 无 K 线数据: {symbol}, 返回默认价格")
                return Decimal("0")
    
    async def place_order(self, order: OrderRequest) -> OrderResult:
        """
        下单
        
        市价单: 立即成交
        限价单: TODO - 挂单逻辑
        """
        try:
            mark_price = await self.get_mark_price(order.symbol)
            
            if mark_price == 0:
                return OrderResult(
                    success=False,
                    error_message=f"无法获取 {order.symbol} 价格"
                )
            
            if order.order_type == OrderType.MARKET:
                # 市价单: 立即以标记价格成交
                commission = order.quantity * mark_price * Decimal("0.0004")  # 0.04% 手续费
                
                logger.info(
                    f"[Simulator] 市价单成交: {order.symbol} {order.side.value} "
                    f"{order.quantity} @ {mark_price}"
                )
                
                return OrderResult(
                    success=True,
                    order_id=f"SIM_{order.symbol}_{order.side.value}",
                    filled_price=mark_price,
                    filled_quantity=order.quantity,
                    commission=commission,
                )
                
            elif order.order_type == OrderType.LIMIT:
                # 限价单: 检查是否可以立即成交
                if order.price is None:
                    return OrderResult(
                        success=False,
                        error_message="限价单需要指定价格"
                    )
                
                # 检查价格是否满足成交条件
                can_fill = False
                if order.side.value == "buy" and order.price >= mark_price:
                    can_fill = True
                elif order.side.value == "sell" and order.price <= mark_price:
                    can_fill = True
                
                if can_fill:
                    commission = order.quantity * order.price * Decimal("0.0002")  # Maker 0.02%
                    
                    logger.info(
                        f"[Simulator] 限价单成交: {order.symbol} {order.side.value} "
                        f"{order.quantity} @ {order.price}"
                    )
                    
                    return OrderResult(
                        success=True,
                        order_id=f"SIM_{order.symbol}_{order.side.value}_LIMIT",
                        filled_price=order.price,
                        filled_quantity=order.quantity,
                        commission=commission,
                    )
                else:
                    # 挂单 (TODO: 实现挂单队列)
                    logger.info(
                        f"[Simulator] 限价单挂单: {order.symbol} {order.side.value} "
                        f"{order.quantity} @ {order.price}"
                    )
                    return OrderResult(
                        success=True,
                        order_id=f"SIM_{order.symbol}_{order.side.value}_PENDING",
                        filled_price=None,
                        filled_quantity=Decimal("0"),
                    )
            else:
                return OrderResult(
                    success=False,
                    error_message=f"暂不支持订单类型: {order.order_type}"
                )
                
        except Exception as e:
            logger.error(f"[Simulator] 下单失败: {e}")
            return OrderResult(
                success=False,
                error_message=str(e)
            )
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """撤单"""
        logger.info(f"[Simulator] 撤单: {order_id}")
        # TODO: 从挂单队列中移除
        return True
    
    async def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """获取仓位"""
        # TODO: 从数据库读取 Position 表
        return None
    
    async def get_balance(self) -> Decimal:
        """获取余额"""
        # TODO: 从数据库读取 Wallet 表
        return Decimal("10000")
