"""
Order Executor Service
=======================
订单执行器 - 处理订单的创建、执行和生命周期管理

职责:
1. 创建订单 (冻结保证金)
2. 执行市价单 (调用 PositionManager 开仓/平仓)
3. 执行限价单 (挂单等待成交)
4. 执行条件单 (等待触发价格)
5. 取消订单 (释放保证金)

订单执行流程:
1. MARKET: 创建 → 立即执行 → 开/平仓 → FILLED
2. LIMIT: 创建 → 挂单 → 等待价格 → 执行 → FILLED
3. STOP/TP: 创建 → 等待触发 → 触发后按 MARKET/LIMIT 执行
"""

from decimal import Decimal
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.order import Order, OrderSide, OrderType, OrderStatus, PositionSideEnum
from app.models.position import Position, PositionSide, PositionStatus
from app.services.trading import PositionManager, InsufficientMarginError
from app.services.wallet import WalletManager, InsufficientFundsError
from app.services.trading.fee_calculator import FeeCalculator


class OrderError(Exception):
    """订单异常"""
    pass


class OrderNotFoundError(OrderError):
    """订单不存在"""
    def __init__(self, order_id: int):
        super().__init__(f"Order not found: {order_id}")


class InvalidOrderError(OrderError):
    """无效订单"""
    pass


class OrderExecutor:
    """
    订单执行器
    
    核心方法:
    - create_order: 创建订单 (冻结保证金)
    - execute_market_order: 执行市价单
    - cancel_order: 取消订单 (释放保证金)
    - check_conditional_orders: 检查条件单触发
    """
    
    @staticmethod
    def calculate_required_margin(
        quantity: Decimal,
        price: Decimal,
        leverage: int,
    ) -> Decimal:
        """
        计算下单所需保证金 (不含手续费)
        
        保证金 = (数量 × 价格) / 杠杆
        """
        notional = quantity * price
        return notional / Decimal(leverage)
    
    @staticmethod
    def calculate_open_cost(
        quantity: Decimal,
        price: Decimal,
        leverage: int,
        is_maker: bool = False,
    ) -> tuple[Decimal, Decimal]:
        """
        计算开仓总成本 (含手续费)
        
        Cost = Initial Margin + Commission
        币安公式: Notional = qty × price
        
        Returns:
            (initial_margin, commission)
        """
        return FeeCalculator.calculate_open_cost(quantity, price, leverage, is_maker)
    
    @staticmethod
    async def create_order(
        db: AsyncSession,
        user_id: int,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        trigger_price: Optional[Decimal] = None,
        leverage: int = 1,
        position_side: Optional[PositionSideEnum] = None,
        reduce_only: bool = False,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        note: Optional[str] = None,
    ) -> Order:
        """
        创建订单
        
        流程:
        1. 验证订单参数
        2. 计算所需保证金 (非 reduce_only 订单)
        3. 冻结保证金
        4. 创建订单记录
        5. 如果是市价单，立即执行
        
        Returns:
            创建的 Order 实例
        """
        # 1. 参数验证
        if order_type == OrderType.LIMIT and price is None:
            raise InvalidOrderError("Limit order requires price")
        
        if order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT, 
                          OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT_LIMIT):
            if trigger_price is None:
                raise InvalidOrderError("Conditional order requires trigger_price")
        
        if order_type == OrderType.STOP_LIMIT and price is None:
            raise InvalidOrderError("Stop limit order requires price")
        
        # 确定仓位方向
        if position_side is None:
            position_side = PositionSideEnum.LONG if side == OrderSide.BUY else PositionSideEnum.SHORT
        
        logger.info(
            f"[OrderExecutor] Creating order: user={user_id}, "
            f"{symbol} {side.value} {order_type.value} qty={quantity}, "
            f"price={price}, trigger={trigger_price}, leverage={leverage}x"
        )
        
        # 2. 计算保证金 + 手续费 (只有开仓需要)
        margin_required = Decimal("0")
        commission_estimate = Decimal("0")
        ref_price = price or trigger_price
        
        # 🔥 市价单: 必须获取实时价格
        if ref_price is None:
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            try:
                ticker = await client.get_ticker(symbol)
                if ticker:
                    ref_price = Decimal(ticker.get("lastPrice", "0"))
                    logger.info(f"[OrderExecutor] Fetched market price for {symbol}: {ref_price}")
            except Exception as e:
                logger.warning(f"[OrderExecutor] Failed to get market price: {e}")
        
        if ref_price is None or ref_price <= 0:
            raise OrderError(f"Cannot determine price for {symbol}. Market data unavailable.")
        
        # 判断 Maker/Taker: 市价=Taker, 限价=Maker
        is_maker = order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT, OrderType.TAKE_PROFIT_LIMIT)
        
        total_freeze = Decimal("0")  # 默认值 (reduce_only 订单不冻结)
        
        if not reduce_only:
            margin_required, commission_estimate = OrderExecutor.calculate_open_cost(
                quantity, ref_price, leverage, is_maker
            )
            total_freeze = margin_required + commission_estimate
        
        # 🔥 Fix #5: 使用 savepoint 保证 freeze + create 的原子性
        # 如果 flush 失败, freeze 也会回滚
        async with db.begin_nested():
            if total_freeze > 0:
                try:
                    await WalletManager.freeze_funds(db, user_id, total_freeze)
                    logger.info(
                        f"[OrderExecutor] Frozen: {total_freeze} USDT "
                        f"(margin={margin_required}, commission={commission_estimate})"
                    )
                except InsufficientFundsError as e:
                    raise OrderError(
                        f"Insufficient funds: required={total_freeze} "
                        f"(margin={margin_required} + fee={commission_estimate}), "
                        f"available={e.available}"
                    )
            
            # 4. 创建订单 (记录冻结金额用于精确解冻)
            order = Order(
                user_id=user_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                status=OrderStatus.PENDING,
                leverage=leverage,
                position_side=position_side,
                reduce_only=reduce_only,
                price=price,
                trigger_price=trigger_price,
                quantity=quantity,
                stop_loss=stop_loss,
                take_profit=take_profit,
                note=note,
                frozen_amount=total_freeze,
            )
            
            db.add(order)
            await db.flush()
        
        logger.info(f"[OrderExecutor] Order created: id={order.id}, frozen={total_freeze}")
        
        # 5. 市价单立即执行
        if order_type == OrderType.MARKET:
            await OrderExecutor.execute_market_order(db, order, ref_price)
        elif order_type == OrderType.LIMIT:
            # 🔥 优化: 检查是否可以立即成交
            # 获取当前市场价格
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            try:
                ticker = await client.get_ticker(symbol)
                if ticker:
                    current_price = Decimal(ticker.get("lastPrice", "0"))
                    
                    # 判断是否满足成交条件
                    should_fill_now = False
                    if side == OrderSide.BUY and current_price <= price:
                        # 买入限价单: 当前价格 <= 限价 → 立即成交
                        should_fill_now = True
                    elif side == OrderSide.SELL and current_price >= price:
                        # 卖出限价单: 当前价格 >= 限价 → 立即成交
                        should_fill_now = True
                    
                    if should_fill_now:
                        logger.info(
                            f"[OrderExecutor] Limit order instant fill: "
                            f"limit={price}, current={current_price}"
                        )
                        await OrderExecutor.execute_market_order(db, order, price)
                    else:
                        order.transition_to(OrderStatus.OPEN)
                else:
                    # 无法获取价格，挂单等待
                    order.transition_to(OrderStatus.OPEN)
            except Exception as e:
                logger.warning(f"[OrderExecutor] Price check failed, placing as pending: {e}")
                order.transition_to(OrderStatus.OPEN)
        else:
            # 条件单等待触发
            order.transition_to(OrderStatus.PENDING)
        
        return order
    
    @staticmethod
    async def execute_market_order(
        db: AsyncSession,
        order: Order,
        execution_price: Decimal,
    ) -> Order:
        """
        执行市价单
        
        流程:
        1. 市价单应用滑点 → 实际成交价
        2. 根据 reduce_only 决定开仓或平仓
        3. 计算并记录手续费
        """
        # 🔥 市价单应用滑点 (限价单不应用)
        is_market = order.order_type == OrderType.MARKET
        if is_market:
            side_str = "buy" if order.side == OrderSide.BUY else "sell"
            actual_price = FeeCalculator.apply_slippage(execution_price, side_str)
            logger.info(
                f"[OrderExecutor] Slippage applied: {execution_price} → {actual_price} "
                f"({side_str})"
            )
        else:
            actual_price = execution_price
        
        # 判断 Maker/Taker
        is_maker = not is_market
        
        # 计算手续费
        commission = FeeCalculator.calculate_commission(
            order.quantity, actual_price, is_maker
        )
        
        logger.info(
            f"[OrderExecutor] Executing order: id={order.id}, "
            f"price={actual_price}, commission={commission}"
        )
        
        if order.reduce_only:
            # 平仓
            await OrderExecutor._execute_close_position(
                db, order, actual_price, commission
            )
        else:
            # 开仓
            await OrderExecutor._execute_open_position(
                db, order, actual_price, commission
            )
        
        # 更新订单状态
        order.transition_to(OrderStatus.FILLED)
        order.filled_quantity = order.quantity
        order.avg_fill_price = actual_price
        order.commission = commission
        order.filled_at = datetime.utcnow()
        
        return order
    
    @staticmethod
    async def _execute_open_position(
        db: AsyncSession,
        order: Order,
        price: Decimal,
        commission: Decimal = Decimal("0"),
    ) -> None:
        """执行开仓 (含手续费扣除)
        
        资金流 (优化后):
        1. 冻结中扣除手续费 (frozen -= commission, 不退回balance)
        2. 剩余冻结直接转为仓位保证金 (无需 unfreeze→re-freeze)
        """
        # 确定仓位方向
        pos_side = PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT
        
        # 🔥 从冻结金额中扣除手续费 (不经过 balance)
        if commission > 0:
            wallet = await WalletManager.get_wallet(db, order.user_id, for_update=True)
            wallet.frozen -= commission
            # 手续费直接作为成本消耗, 不退回 balance
            logger.info(
                f"[OrderExecutor] Fee deducted from frozen: {commission} USDT, "
                f"remaining frozen for margin: {order.frozen_amount - commission}"
            )
        
        # 计算仓位保证金 (按实际成交价)
        margin_for_position = OrderExecutor.calculate_required_margin(
            order.quantity, price, order.leverage
        )
        
        # 如果冻结金额 > 保证金+手续费 (因为冻结是按预估价), 退还差额
        remaining_frozen = order.frozen_amount - commission
        if remaining_frozen > margin_for_position:
            excess = remaining_frozen - margin_for_position
            wallet = await WalletManager.get_wallet(db, order.user_id, for_update=True)
            wallet.frozen -= excess
            wallet.balance += excess
            logger.info(f"[OrderExecutor] Excess frozen returned: {excess} USDT")
        elif remaining_frozen < margin_for_position:
            # 需要额外冻结 (实际成交价高于预估)
            shortfall = margin_for_position - remaining_frozen
            await WalletManager.freeze_funds(db, order.user_id, shortfall)
            logger.info(f"[OrderExecutor] Additional margin frozen: {shortfall} USDT")
        
        # 清除订单冻结记录 (已转为仓位保证金)
        order.frozen_amount = Decimal("0")
        
        # 确定交易来源 (从 order.note 解析)
        source = "manual"
        open_reason = None
        if order.note:
            note = order.note
            if note.startswith("[Agent]"):
                source = "agent"
                open_reason = note[7:].strip()
            elif note.startswith("[Autopilot]"):
                source = "autopilot"
                open_reason = note[11:].strip()
            elif note.startswith("[AutoPilot]"):
                source = "autopilot"
                open_reason = note[11:].strip()
            elif note.startswith("[Signal]"):
                source = "signal"
                open_reason = note[8:].strip()
            else:
                open_reason = note
        
        # 调用 PositionManager 开仓 (保证金已在冻结中, skip_freeze=True)
        position = await PositionManager.open_position(
            db=db,
            user_id=order.user_id,
            symbol=order.symbol,
            side=pos_side,
            quantity=order.quantity,
            entry_price=price,
            leverage=order.leverage,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            source=source,
            open_reason=open_reason,
            commission=commission,
            pre_frozen_margin=margin_for_position,  # 🔥 跳过 PositionManager 重复冻结
        )
        
        order.position_id = position.id
        logger.info(
            f"[OrderExecutor] Position opened: id={position.id}, "
            f"commission={commission}"
        )
    
    @staticmethod
    async def _execute_close_position(
        db: AsyncSession,
        order: Order,
        price: Decimal,
        commission: Decimal = Decimal("0"),
    ) -> None:
        """执行平仓 (含手续费扣除)"""
        # 查找用户的仓位
        pos_side = PositionSide.LONG if order.side == OrderSide.SELL else PositionSide.SHORT
        
        position = await PositionManager.get_open_position(
            db, order.user_id, order.symbol, pos_side
        )
        
        if not position:
            raise OrderError(f"No open position to close: {order.symbol} {pos_side.value}")
        
        # 调用 PositionManager 平仓 (含手续费)
        position, pnl = await PositionManager.close_position(
            db=db,
            position_id=position.id,
            close_price=price,
            close_quantity=order.quantity,
            commission=commission,
        )
        
        order.position_id = position.id
        order.realized_pnl = pnl
        logger.info(
            f"[OrderExecutor] Position closed: pnl={pnl}, "
            f"commission={commission}"
        )
    
    @staticmethod
    async def cancel_order(
        db: AsyncSession,
        order_id: int,
        user_id: int,
    ) -> Order:
        """
        取消订单
        
        流程:
        1. 验证订单状态
        2. 释放冻结的保证金
        3. 更新订单状态
        """
        # 获取订单
        result = await db.execute(
            select(Order).where(
                and_(
                    Order.id == order_id,
                    Order.user_id == user_id,
                )
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        
        if not order:
            raise OrderNotFoundError(order_id)
        
        if not order.is_active:
            raise OrderError(f"Order cannot be cancelled: status={order.status.value}")
        
        logger.info(f"[OrderExecutor] Cancelling order: id={order_id}")
        
        # 释放保证金 (使用精确冻结金额, 不再重新计算)
        if order.frozen_amount > 0:
            await WalletManager.unfreeze_funds(db, user_id, order.frozen_amount)
            logger.info(
                f"[OrderExecutor] Released frozen: {order.frozen_amount} USDT"
            )
            order.frozen_amount = Decimal("0")
        
        order.transition_to(OrderStatus.CANCELLED)
        return order
    
    @staticmethod
    async def get_user_orders(
        db: AsyncSession,
        user_id: int,
        status: Optional[OrderStatus] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Order]:
        """获取用户订单列表"""
        query = select(Order).where(Order.user_id == user_id)
        
        if status:
            query = query.where(Order.status == status)
        if symbol:
            query = query.where(Order.symbol == symbol)
        
        query = query.order_by(Order.created_at.desc()).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def check_conditional_orders(
        db: AsyncSession,
        symbol: str,
        current_price: Decimal,
    ) -> List[Order]:
        """
        检查条件单触发
        
        当价格达到触发条件时，执行对应的订单
        
        Returns:
            触发并执行的订单列表
        """
        triggered_orders = []
        
        # 查找该交易对的待触发条件单
        result = await db.execute(
            select(Order).where(
                and_(
                    Order.symbol == symbol,
                    Order.status == OrderStatus.PENDING,
                    Order.trigger_price.isnot(None),
                )
            )
        )
        pending_orders = result.scalars().all()
        
        for order in pending_orders:
            triggered = False
            
            if order.order_type in (OrderType.STOP_MARKET, OrderType.STOP_LIMIT):
                # 止损单: 多单价格跌破触发价 / 空单价格涨破触发价
                if order.position_side == PositionSideEnum.LONG:
                    triggered = current_price <= order.trigger_price
                else:
                    triggered = current_price >= order.trigger_price
                    
            elif order.order_type in (OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT_LIMIT):
                # 止盈单: 多单价格涨破触发价 / 空单价格跌破触发价
                if order.position_side == PositionSideEnum.LONG:
                    triggered = current_price >= order.trigger_price
                else:
                    triggered = current_price <= order.trigger_price
            
            if triggered:
                logger.info(
                    f"[OrderExecutor] Conditional order triggered: "
                    f"id={order.id}, trigger={order.trigger_price}, current={current_price}"
                )
                
                if order.order_type in (OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET):
                    # 市价执行
                    await OrderExecutor.execute_market_order(db, order, current_price)
                else:
                    # 转换为限价单
                    order.transition_to(OrderStatus.OPEN)
                
                triggered_orders.append(order)
        
        return triggered_orders
    
    @staticmethod
    async def check_limit_orders(
        db: AsyncSession,
        symbol: str,
        current_price: Decimal,
    ) -> List[Order]:
        """
        检查限价单成交条件
        
        限价单成交规则:
        - BUY LIMIT: 当前价格 <= 限价 → 成交
        - SELL LIMIT: 当前价格 >= 限价 → 成交
        
        Returns:
            已成交的订单列表
        """
        filled_orders = []
        
        # 查找该交易对的挂单 (OPEN 状态的 LIMIT 订单)
        result = await db.execute(
            select(Order).where(
                and_(
                    Order.symbol == symbol,
                    Order.status == OrderStatus.OPEN,
                    Order.order_type == OrderType.LIMIT,
                )
            )
        )
        open_orders = result.scalars().all()
        
        for order in open_orders:
            should_fill = False
            
            if order.side == OrderSide.BUY:
                # 买入限价单: 当前价格 <= 限价 → 成交
                # (你愿意付更高价格，所以用市价成交更划算)
                should_fill = current_price <= order.price
            else:
                # 卖出限价单: 当前价格 >= 限价 → 成交
                # (市价更高，用市价成交更划算)
                should_fill = current_price >= order.price
            
            if should_fill:
                logger.info(
                    f"[OrderExecutor] Limit order filled: "
                    f"id={order.id}, side={order.side.value}, "
                    f"limit_price={order.price}, current={current_price}"
                )
                
                # 以限价成交 (保证用户得到预期价格)
                await OrderExecutor.execute_market_order(db, order, order.price)
                filled_orders.append(order)
        
        return filled_orders

    @staticmethod
    async def check_position_sl_tp(
        db: AsyncSession,
        symbol: str,
        current_price: Decimal,
    ) -> List[Position]:
        """
        🔥 检查仓位止损/止盈触发
        
        规则 (币安标准):
        - LONG 止损: current_price <= stop_loss → 平仓
        - LONG 止盈: current_price >= take_profit → 平仓
        - SHORT 止损: current_price >= stop_loss → 平仓
        - SHORT 止盈: current_price <= take_profit → 平仓
        
        Args:
            db: 数据库会话
            symbol: 交易对
            current_price: 当前标记价格
            
        Returns:
            已触发平仓的仓位列表
        """
        from app.services.trading.fee_calculator import FeeCalculator
        
        # 查询该交易对的所有开放仓位 (有止损或止盈的)
        result = await db.execute(
            select(Position).where(
                and_(
                    Position.symbol == symbol,
                    Position.status == PositionStatus.OPEN,
                    or_(
                        Position.stop_loss.isnot(None),
                        Position.take_profit.isnot(None),
                    ),
                )
            )
        )
        positions = result.scalars().all()
        
        closed_positions = []
        
        for position in positions:
            triggered = False
            trigger_reason = ""
            
            if position.side == PositionSide.LONG:
                # 多仓止损: 价格跌破止损价
                if position.stop_loss and current_price <= position.stop_loss:
                    triggered = True
                    trigger_reason = f"SL triggered: price {current_price} <= SL {position.stop_loss}"
                # 多仓止盈: 价格涨破止盈价
                elif position.take_profit and current_price >= position.take_profit:
                    triggered = True
                    trigger_reason = f"TP triggered: price {current_price} >= TP {position.take_profit}"
            else:
                # 空仓止损: 价格涨破止损价
                if position.stop_loss and current_price >= position.stop_loss:
                    triggered = True
                    trigger_reason = f"SL triggered: price {current_price} >= SL {position.stop_loss}"
                # 空仓止盈: 价格跌破止盈价
                elif position.take_profit and current_price <= position.take_profit:
                    triggered = True
                    trigger_reason = f"TP triggered: price {current_price} <= TP {position.take_profit}"
            
            if triggered:
                logger.warning(
                    f"[OrderExecutor] ⚠️ Position SL/TP triggered: "
                    f"id={position.id}, {position.symbol} {position.side.value}, "
                    f"{trigger_reason}"
                )
                
                try:
                    # 计算平仓手续费 (市价平仓 = Taker)
                    commission = FeeCalculator.calculate_commission(
                        position.size, current_price, is_maker=False
                    )
                    
                    # 确定平仓原因
                    close_reason = "stop_loss" if "SL" in trigger_reason else "take_profit"
                    
                    # 执行平仓
                    closed_pos, pnl = await PositionManager.close_position(
                        db=db,
                        position_id=position.id,
                        close_price=current_price,
                        commission=commission,
                    )
                    
                    closed_positions.append(closed_pos)
                    
                    logger.warning(
                        f"[OrderExecutor] ✅ SL/TP close executed: "
                        f"id={position.id}, pnl={pnl}, commission={commission}, "
                        f"reason={close_reason}"
                    )
                    
                except Exception as e:
                    logger.error(
                        f"[OrderExecutor] SL/TP close failed: "
                        f"position_id={position.id}, error={e}"
                    )
        
        return closed_positions


