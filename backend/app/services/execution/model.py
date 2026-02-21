"""
Execution Model — 执行层
=========================
LEAN 风格: 将 PortfolioTarget 转换为实际订单

职责:
1. 接收 Risk-approved PortfolioTarget
2. 调用现有 OrderExecutor 执行下单
3. 通过 EventBus 广播执行结果

与现有 OrderExecutor 的关系:
- OrderExecutor 保持不变 (底层执行)
- ExecutionModel 是新的入口 (包装 + 事件化)
"""

from decimal import Decimal
from typing import Optional

from loguru import logger

from app.services.portfolio.model import PortfolioTarget, TargetAction
from app.core.event_bus import event_bus, Event, EventType


class ExecutionModel:
    """
    执行模型 — 四层流水线的最终环节
    
    功能:
    1. 将 PortfolioTarget 转换为 OrderExecutor 参数
    2. 执行下单
    3. 发布 ORDER_CREATED / ORDER_FILLED 事件
    """
    
    async def execute(
        self,
        target: PortfolioTarget,
        db,               # AsyncSession
        user_id: int,
    ) -> dict:
        """
        执行交易目标
        
        Args:
            target: 风控审批通过的 PortfolioTarget
            db: 数据库会话
            user_id: 用户 ID
        
        Returns:
            执行结果 dict (包含 order_id 等信息)
        """
        from app.services.trading import OrderExecutor
        from app.models.order import OrderSide, OrderType
        
        try:
            # 1. 转换参数
            if target.action == TargetAction.OPEN_LONG:
                side = OrderSide.BUY
            elif target.action == TargetAction.OPEN_SHORT:
                side = OrderSide.SELL
            elif target.action == TargetAction.CLOSE:
                # 平仓走 PositionManager, 这里暂不处理
                return {"success": False, "error": "平仓请使用 close_position"}
            else:
                side = OrderSide.BUY  # INCREASE/REDUCE 暂按买卖处理
            
            # 2. 来源标记
            source_label = target.source or "pipeline"
            note = f"[Pipeline:{source_label}] {target.insight.source if target.insight else 'manual'}"
            
            # 3. 执行下单  
            order = await OrderExecutor.create_order(
                db=db,
                user_id=user_id,
                symbol=target.symbol,
                side=side,
                order_type=OrderType.MARKET,     # Pipeline 默认市价单
                quantity=target.quantity,
                leverage=target.leverage,
                stop_loss=target.stop_loss_price,
                take_profit=target.take_profit_price,
                note=note,
            )
            
            # 4. 发布事件
            await event_bus.emit(Event(
                type=EventType.ORDER_CREATED,
                data={
                    "order_id": order.id,
                    "symbol": target.symbol,
                    "side": side.value,
                    "quantity": float(target.quantity),
                    "leverage": target.leverage,
                    "source": source_label,
                },
                source="execution_model",
                user_id=user_id,
            ))
            
            result = {
                "success": True,
                "order_id": order.id,
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": float(order.quantity),
                "leverage": order.leverage,
                "status": order.status.value,
                "avg_fill_price": float(order.avg_fill_price) if order.avg_fill_price else None,
            }
            
            logger.info(
                f"[Execution] ✅ Order #{order.id} created: "
                f"{order.side.value} {order.symbol} "
                f"qty={order.quantity} @ {order.avg_fill_price}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[Execution] ❌ Failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "symbol": target.symbol,
            }
