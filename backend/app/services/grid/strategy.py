"""
Grid Strategy Service
======================
网格交易策略服务

核心功能:
1. 计算网格级别和价格
2. 生成网格订单
3. 处理订单成交
4. 监控网格状态

网格执行逻辑:
1. 创建时: 根据参数计算所有网格价格
2. 启动时: 在当前价格下方挂买单，上方挂卖单
3. 买单成交后: 在更高一级挂卖单
4. 卖单成交后: 在更低一级挂买单
5. 持续循环直到停止或触发止盈/止损
"""

from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from loguru import logger

from app.models.grid_bot import GridBot, GridType, GridStatus, GridDirection
from app.models.order import Order, OrderSide, OrderType, OrderStatus
from app.services.trading import OrderExecutor, OrderError
from app.services.wallet import WalletManager
from app.services.trade_journal import TradeJournal


@dataclass
class GridLevel:
    """单个网格级别"""
    level: int
    price: Decimal
    buy_order_id: Optional[int] = None
    sell_order_id: Optional[int] = None
    status: str = "pending"  # pending, buy_placed, filled, sell_placed, matched


class GridError(Exception):
    """网格异常"""
    pass


class GridStrategy:
    """
    网格交易策略
    
    核心方法:
    - create_grid_bot: 创建网格机器人
    - start_grid: 启动网格
    - stop_grid: 停止网格
    - on_order_filled: 订单成交回调
    - monitor_grids: 监控所有网格
    """
    
    @staticmethod
    def calculate_grid_prices(
        lower_price: Decimal,
        upper_price: Decimal,
        grid_count: int,
        grid_type: GridType,
    ) -> Tuple[List[Decimal], Decimal]:
        """
        计算网格价格列表
        
        Args:
            lower_price: 下边界
            upper_price: 上边界
            grid_count: 网格数量
            grid_type: 网格类型
            
        Returns:
            (价格列表, 网格间距)
        """
        prices = []
        
        if grid_type == GridType.ARITHMETIC:
            # 等差网格: 价格等距
            interval = (upper_price - lower_price) / Decimal(grid_count)
            for i in range(grid_count + 1):
                price = lower_price + interval * Decimal(i)
                prices.append(price.quantize(Decimal("0.01")))
            return prices, interval
        else:
            # 等比网格: 每格涨跌相同百分比
            import math
            ratio = (float(upper_price) / float(lower_price)) ** (1 / grid_count)
            interval = Decimal(str((ratio - 1) * 100))  # 百分比
            for i in range(grid_count + 1):
                price = lower_price * Decimal(str(ratio ** i))
                prices.append(price.quantize(Decimal("0.01")))
            return prices, interval
    
    @staticmethod
    def calculate_quantity_per_grid(
        investment: Decimal,
        grid_count: int,
        avg_price: Decimal,
        leverage: int,
    ) -> Decimal:
        """
        计算每格交易数量
        
        每格投入 = 总投入 / 网格数
        有效名义价值 = 每格投入 × 杠杆
        数量 = 有效名义价值 / 平均价格
        """
        per_grid_investment = investment / Decimal(grid_count)
        notional = per_grid_investment * Decimal(leverage)
        quantity = notional / avg_price
        return quantity.quantize(Decimal("0.00001"))  # 5 位小数
    
    @staticmethod
    async def create_grid_bot(
        db: AsyncSession,
        user_id: int,
        name: str,
        symbol: str,
        lower_price: Decimal,
        upper_price: Decimal,
        grid_count: int,
        investment: Decimal,
        leverage: int = 1,
        grid_type: GridType = GridType.ARITHMETIC,
        direction: GridDirection = GridDirection.LONG,
        stop_loss_price: Optional[Decimal] = None,
        take_profit_price: Optional[Decimal] = None,
    ) -> GridBot:
        """
        创建网格机器人
        
        流程:
        1. 验证参数
        2. 计算网格级别
        3. 冻结投资金额
        4. 创建 GridBot 记录
        """
        # 参数验证
        if upper_price <= lower_price:
            raise GridError("上边界必须大于下边界")
        if grid_count < 2 or grid_count > 200:
            raise GridError("网格数量必须在 2-200 之间")
        if investment <= 0:
            raise GridError("投资金额必须大于 0")
        
        logger.info(
            f"[GridStrategy] Creating grid bot: {name}, "
            f"symbol={symbol}, range=[{lower_price}, {upper_price}], "
            f"grids={grid_count}, investment={investment}"
        )
        
        # 计算网格价格
        prices, interval = GridStrategy.calculate_grid_prices(
            lower_price, upper_price, grid_count, grid_type
        )
        
        # 计算每格数量
        avg_price = (lower_price + upper_price) / 2
        quantity_per_grid = GridStrategy.calculate_quantity_per_grid(
            investment, grid_count, avg_price, leverage
        )
        
        # 构建网格级别数据
        grid_levels = [
            {
                "level": i,
                "price": str(price),
                "buy_order_id": None,
                "sell_order_id": None,
                "status": "pending",
            }
            for i, price in enumerate(prices)
        ]
        
        # 注意: 不在此处冻结投资金额
        # 每个订单在 OrderExecutor.create_order 中单独冻结保证金+手续费
        # 避免双重冻结
        
        # 创建 GridBot
        bot = GridBot(
            user_id=user_id,
            name=name,
            symbol=symbol,
            grid_type=grid_type,
            direction=direction,
            status=GridStatus.CREATED,
            upper_price=upper_price,
            lower_price=lower_price,
            grid_count=grid_count,
            investment=investment,
            leverage=leverage,
            grid_interval=interval,
            quantity_per_grid=quantity_per_grid,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            grid_levels=grid_levels,
        )
        
        db.add(bot)
        await db.flush()
        
        logger.info(f"[GridStrategy] Grid bot created: id={bot.id}")
        return bot
    
    @staticmethod
    async def start_grid(
        db: AsyncSession,
        bot_id: int,
        current_price: Decimal,
    ) -> GridBot:
        """
        启动网格
        
        根据当前价格在网格区间内放置订单:
        - 当前价格以下: 放置买单
        - 当前价格以上: 放置卖单 (需要先有仓位)
        """
        result = await db.execute(
            select(GridBot).where(GridBot.id == bot_id).with_for_update()
        )
        bot = result.scalar_one_or_none()
        
        if not bot:
            raise GridError(f"Grid bot not found: {bot_id}")
        
        if bot.status not in (GridStatus.CREATED, GridStatus.PAUSED, GridStatus.STOPPED):
            raise GridError(f"Grid bot cannot start: status={bot.status.value}")
        
        logger.info(f"[GridStrategy] Starting grid bot: id={bot_id}, current_price={current_price}")
        
        # 找到当前价格对应的级别
        grid_levels = bot.grid_levels or []
        current_level = 0
        
        # 计算区间中点
        midpoint = (bot.upper_price + bot.lower_price) / 2
        
        logger.info(f"[GridStrategy] Zone grid: range=[{bot.lower_price}, {bot.upper_price}], midpoint={midpoint}")
        
        # 记录当前价格位置 (仍然用于显示)
        for i, level in enumerate(grid_levels):
            if Decimal(level["price"]) <= current_price:
                current_level = i
        bot.current_level = current_level
        
        # ========================================
        # 区域网格逻辑 (Mode B)
        # ========================================
        # 下半区 (低于中点) → 全部放置买单
        # 上半区 (高于中点) → 全部放置卖单
        # ========================================
        
        buy_count = 0
        sell_count = 0
        
        for level in grid_levels:
            level_price = Decimal(level["price"])
            
            if level["status"] != "pending":
                continue
            
            # 下半区: 放置买单 (低买)
            if level_price < midpoint:
                try:
                    order = await OrderExecutor.create_order(
                        db=db,
                        user_id=bot.user_id,
                        symbol=bot.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        quantity=bot.quantity_per_grid,
                        price=level_price,
                        leverage=bot.leverage,
                        note=f"Grid #{bot.id} L{level['level']} BUY",
                    )
                    level["buy_order_id"] = order.id
                    level["status"] = "buy_placed"
                    buy_count += 1
                except OrderError as e:
                    logger.warning(f"[GridStrategy] Failed to place buy order: {e}")
            
            # 上半区: 放置卖单 (高卖)
            elif level_price >= midpoint:
                try:
                    order = await OrderExecutor.create_order(
                        db=db,
                        user_id=bot.user_id,
                        symbol=bot.symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=bot.quantity_per_grid,
                        price=level_price,
                        leverage=bot.leverage,
                        note=f"Grid #{bot.id} L{level['level']} SELL",
                    )
                    level["sell_order_id"] = order.id
                    level["status"] = "sell_placed"
                    sell_count += 1
                except OrderError as e:
                    logger.warning(f"[GridStrategy] Failed to place sell order: {e}")
        
        bot.status = GridStatus.RUNNING
        bot.started_at = datetime.utcnow()
        bot.grid_levels = grid_levels
        flag_modified(bot, "grid_levels")
        
        logger.info(f"[GridStrategy] Grid started: {buy_count} buy orders, {sell_count} sell orders")
        return bot
    
    @staticmethod
    async def stop_grid(
        db: AsyncSession,
        bot_id: int,
        cancel_orders: bool = True,
    ) -> GridBot:
        """
        停止网格
        
        流程:
        1. 取消所有挂单
        2. 释放冻结资金
        3. 更新状态
        """
        result = await db.execute(
            select(GridBot).where(GridBot.id == bot_id).with_for_update()
        )
        bot = result.scalar_one_or_none()
        
        if not bot:
            raise GridError(f"Grid bot not found: {bot_id}")
        
        logger.info(f"[GridStrategy] Stopping grid bot: id={bot_id}")
        
        # 取消所有挂单
        if cancel_orders:
            grid_levels = bot.grid_levels or []
            for level in grid_levels:
                if level.get("buy_order_id"):
                    try:
                        await OrderExecutor.cancel_order(db, level["buy_order_id"], bot.user_id)
                    except Exception as e:
                        logger.warning(f"[GridStrategy] Failed to cancel order: {e}")
                
                if level.get("sell_order_id"):
                    try:
                        await OrderExecutor.cancel_order(db, level["sell_order_id"], bot.user_id)
                    except Exception as e:
                        logger.warning(f"[GridStrategy] Failed to cancel order: {e}")
        
        # ✅ 冻结资金说明:
        # - 每个挂单的 frozen_amount 已通过 cancel_order → unfreeze_funds 精确释放
        # - 已成交订单的保证金已转为仓位 (Position.margin), 由用户手动平仓释放
        # - 无需额外处理
        
        bot.status = GridStatus.STOPPED
        bot.stopped_at = datetime.utcnow()
        
        return bot
    
    @staticmethod
    async def on_order_filled(
        db: AsyncSession,
        order: Order,
    ) -> Optional[Order]:
        """
        订单成交回调
        
        买单成交后: 在上一级放置卖单
        卖单成交后: 在下一级放置买单, 记录利润
        
        Returns:
            新创建的对冲订单
        """
        # 检查是否是网格订单 (start_grid 格式: "Grid #{id} L{level} BUY/SELL")
        if not order.note or "Grid #" not in order.note:
            return None
        
        # 解析 bot_id 和 level (支持两种格式)
        import re
        # 新格式: "Grid #8289 L5 BUY"
        match = re.search(r"Grid #(\d+) L(\d+)", order.note)
        if not match:
            # 旧格式兼容: "Grid bot #123 level 5"
            match = re.search(r"Grid bot #(\d+) level (\d+)", order.note)
        if not match:
            return None
        
        bot_id = int(match.group(1))
        level_num = int(match.group(2))
        
        result = await db.execute(
            select(GridBot).where(GridBot.id == bot_id).with_for_update()
        )
        bot = result.scalar_one_or_none()
        
        if not bot or bot.status != GridStatus.RUNNING:
            return None
        
        grid_levels = bot.grid_levels or []
        level = grid_levels[level_num] if level_num < len(grid_levels) else None
        
        if not level:
            return None
        
        new_order = None
        
        if order.side == OrderSide.BUY:
            # 买单成交: 更新统计, 放置卖单
            bot.filled_buy_count += 1
            level["status"] = "filled"
            
            # 在上一级放置卖单
            if level_num + 1 < len(grid_levels):
                sell_price = Decimal(grid_levels[level_num + 1]["price"])
                try:
                    new_order = await OrderExecutor.create_order(
                        db=db,
                        user_id=bot.user_id,
                        symbol=bot.symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.LIMIT,
                        quantity=bot.quantity_per_grid,
                        price=sell_price,
                        leverage=bot.leverage,
                        reduce_only=True,
                        note=f"Grid #{bot.id} L{level_num} SELL",
                    )
                    level["sell_order_id"] = new_order.id
                    level["status"] = "sell_placed"
                except OrderError as e:
                    logger.warning(f"[GridStrategy] Failed to place sell order: {e}")
        
        elif order.side == OrderSide.SELL:
            # 卖单成交: 记录利润, 放置买单
            bot.filled_sell_count += 1
            level["status"] = "matched"
            
            # 计算该格利润
            buy_price = Decimal(level["price"])
            sell_price = order.avg_fill_price or order.price
            profit = (sell_price - buy_price) * order.quantity
            
            bot.total_profit += profit
            bot.realized_pnl = bot.total_profit - bot.total_fee
            
            logger.info(f"[GridStrategy] Grid matched: profit={profit}, total={bot.total_profit}")
            
            # 记录到交易日志 (TradeJournal)
            try:
                from app.models.position import Position, PositionSide
                # 构造轻量 Position-like 对象供 TradeJournal 使用
                # 网格不创建 Position, 所以用当前 order 的数据构造
                class _GridPseudoPosition:
                    """网格伪仓位 — 仅用于 TradeJournal 记录"""
                    def __init__(self, bot, order, buy_price, sell_price, profit):
                        self.id = None  # 网格无 position_id
                        self.user_id = bot.user_id
                        self.symbol = bot.symbol
                        self.side = PositionSide.LONG if bot.direction.value == "long" else PositionSide.SHORT
                        self.entry_price = buy_price
                        self.margin = buy_price * order.quantity / Decimal(str(bot.leverage))
                        self.size = order.quantity
                        self.leverage = bot.leverage
                        self.created_at = order.created_at
                        self.closed_at = datetime.utcnow()
                        self.stop_loss = bot.stop_loss_price
                        self.take_profit = bot.take_profit_price
                        self.total_commission = Decimal("0")
                        self.source = "grid"
                        self.open_reason = f"Grid #{bot.id}"
                
                pseudo_pos = _GridPseudoPosition(bot, order, buy_price, sell_price, profit)
                await TradeJournal.record_close(
                    db=db,
                    position=pseudo_pos,
                    pnl=profit,
                    close_price=sell_price,
                    close_reason="grid_matched",
                )
            except Exception as e:
                logger.warning(f"[GridStrategy] TradeJournal record failed: {e}")
                
            # 重新在该级放置买单
            try:
                new_order = await OrderExecutor.create_order(
                    db=db,
                    user_id=bot.user_id,
                    symbol=bot.symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=bot.quantity_per_grid,
                    price=buy_price,
                    leverage=bot.leverage,
                    note=f"Grid #{bot.id} L{level_num} BUY",
                )
                level["buy_order_id"] = new_order.id
                level["status"] = "buy_placed"
            except OrderError as e:
                logger.warning(f"[GridStrategy] Failed to place buy order: {e}")
        
        bot.grid_levels = grid_levels
        flag_modified(bot, "grid_levels")
        return new_order
    
    @staticmethod
    async def get_user_grid_bots(
        db: AsyncSession,
        user_id: int,
        status: Optional[GridStatus] = None,
    ) -> List[GridBot]:
        """获取用户所有网格机器人"""
        query = select(GridBot).where(GridBot.user_id == user_id)
        
        if status:
            query = query.where(GridBot.status == status)
        
        query = query.order_by(GridBot.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())
