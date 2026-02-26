"""
Conditional Order Monitor
=========================
右侧条件单监控服务

职责:
1. 监控实时价格
2. 检查 K 线收盘确认
3. 触发条件单执行
4. 处理超时取消
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Dict, Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import (
from app.core.time_utils import utc_now
    TaskTicket, TaskStatus, TradingMode, TradeSide, ConfirmInterval
)
from app.models.market import Kline
from app.services.trading.order_executor import OrderExecutor
from app.models.order import OrderSide, OrderType


class ConditionalOrderMonitor:
    """
    条件单监控器
    
    用于右侧交易的突破确认逻辑
    """
    
    # 监控中的任务
    _monitoring_tasks: Dict[int, asyncio.Task] = {}
    
    @classmethod
    async def start_monitoring(
        cls,
        db: AsyncSession,
        task_id: int,
    ) -> bool:
        """
        开始监控某个条件任务
        
        Args:
            db: 数据库会话
            task_id: 任务ID
            
        Returns:
            是否成功开始监控
        """
        # 获取任务
        task = await db.get(TaskTicket, task_id)
        if not task:
            logger.error(f"[ConditionalMonitor] Task {task_id} not found")
            return False
        
        if task.trading_mode != TradingMode.RIGHT_SIDE:
            logger.error(f"[ConditionalMonitor] Task {task_id} is not a right-side task")
            return False
        
        # 设置过期时间
        if not task.expires_at:
            task.expires_at = utc_now() + timedelta(hours=task.timeout_hours or 24)
        
        # 更新状态为监控中
        task.status = TaskStatus.MONITORING
        await db.commit()
        
        logger.info(f"[ConditionalMonitor] Started monitoring task {task_id}")
        logger.info(f"  - Symbol: {task.symbol}")
        logger.info(f"  - Trade side: {task.trade_side}")
        logger.info(f"  - Trigger price: {task.trigger_price}")
        logger.info(f"  - Expires at: {task.expires_at}")
        
        return True
    
    @classmethod
    async def check_condition(
        cls,
        db: AsyncSession,
        task_id: int,
        current_price: Decimal,
    ) -> bool:
        """
        检查突破条件是否满足
        
        Args:
            db: 数据库会话
            task_id: 任务ID
            current_price: 当前实时价格
            
        Returns:
            True 如果满足执行条件
        """
        task = await db.get(TaskTicket, task_id)
        if not task or task.status != TaskStatus.MONITORING:
            return False
        
        # 检查是否超时
        if task.expires_at and utc_now() > task.expires_at:
            task.status = TaskStatus.EXPIRED
            await db.commit()
            logger.info(f"[ConditionalMonitor] Task {task_id} expired")
            return False
        
        trigger_price = task.trigger_price
        if not trigger_price:
            return False
        
        # 获取条件类型
        from app.models.task import ConditionType
        condition_type = task.condition_type or ConditionType.SIMPLE_BREAKOUT
        phase = task.condition_phase or 1
        
        # ============================================================
        # 简单突破模式 (原逻辑)
        # ============================================================
        if condition_type == ConditionType.SIMPLE_BREAKOUT:
            is_breakout = False
            if task.trade_side == TradeSide.LONG:
                is_breakout = current_price > trigger_price
            elif task.trade_side == TradeSide.SHORT:
                is_breakout = current_price < trigger_price
            
            if not is_breakout:
                return False
        
        # ============================================================
        # 跌破回抽模式 (BREAKDOWN_RECLAIM) - 用于做多
        # 阶段1: 等待价格跌破 trigger_price
        # 阶段2: 等待价格回抽上 trigger_price
        # ============================================================
        elif condition_type == ConditionType.BREAKDOWN_RECLAIM:
            if phase == 1:
                # 阶段1: 等待跌破
                if current_price < trigger_price:
                    logger.info(f"[ConditionalMonitor] Task {task_id}: Phase 1 triggered! Price {current_price} < {trigger_price}")
                    task.condition_phase = 2
                    task.phase1_triggered_at = utc_now()
                    await db.commit()
                return False  # 阶段1完成，但还需等阶段2
            
            elif phase == 2:
                # 阶段2: 等待回抽上来
                if current_price > trigger_price:
                    logger.info(f"[ConditionalMonitor] Task {task_id}: Phase 2 triggered! Price {current_price} > {trigger_price}")
                    # 两阶段都满足，继续检查 K 线确认
                else:
                    return False
        
        # ============================================================
        # 突破回撤模式 (BREAKOUT_PULLBACK) - 用于做空
        # 阶段1: 等待价格突破上 trigger_price
        # 阶段2: 等待价格回撤下 trigger_price
        # ============================================================
        elif condition_type == ConditionType.BREAKOUT_PULLBACK:
            if phase == 1:
                # 阶段1: 等待突破
                if current_price > trigger_price:
                    logger.info(f"[ConditionalMonitor] Task {task_id}: Phase 1 triggered! Price {current_price} > {trigger_price}")
                    task.condition_phase = 2
                    task.phase1_triggered_at = utc_now()
                    await db.commit()
                return False  # 阶段1完成，但还需等阶段2
            
            elif phase == 2:
                # 阶段2: 等待回撤下来
                if current_price < trigger_price:
                    logger.info(f"[ConditionalMonitor] Task {task_id}: Phase 2 triggered! Price {current_price} < {trigger_price}")
                    # 两阶段都满足，继续检查 K 线确认
                else:
                    return False
        
        # 检查偏离是否在允许范围内
        max_dev = task.max_deviation_pct or Decimal("0.5")
        if task.trade_side == TradeSide.LONG:
            max_allowed = trigger_price * (1 + max_dev / 100)
            if current_price > max_allowed:
                logger.debug(f"[ConditionalMonitor] Price {current_price} exceeds max deviation {max_allowed}")
                return False
        else:
            min_allowed = trigger_price * (1 - max_dev / 100)
            if current_price < min_allowed:
                logger.debug(f"[ConditionalMonitor] Price {current_price} below min deviation {min_allowed}")
                return False
        
        # 检查 K 线确认
        kline_confirmed = await cls._check_kline_confirmation(
            db=db,
            symbol=task.symbol,
            trigger_price=trigger_price,
            trade_side=task.trade_side,
            interval=task.confirm_interval or ConfirmInterval.M15,
            confirm_count=task.confirm_count or 1,
        )
        
        if not kline_confirmed:
            logger.debug(f"[ConditionalMonitor] Kline confirmation not met for task {task_id}")
            return False
        
        logger.info(f"[ConditionalMonitor] All conditions met for task {task_id}!")
        return True
    
    @classmethod
    async def _check_kline_confirmation(
        cls,
        db: AsyncSession,
        symbol: str,
        trigger_price: Decimal,
        trade_side: TradeSide,
        interval: ConfirmInterval,
        confirm_count: int,
    ) -> bool:
        """
        检查 K 线收盘确认
        
        Args:
            db: 数据库会话
            symbol: 交易对
            trigger_price: 触发价格
            trade_side: 交易方向
            interval: K 线周期
            confirm_count: 需要确认的 K 线数量
            
        Returns:
            True 如果确认通过
        """
        # 从数据库获取最近的完整 K 线
        query = (
            select(Kline)
            .where(Kline.symbol == symbol.upper())
            .where(Kline.interval == interval.value)
            .order_by(Kline.open_time.desc())
            .limit(confirm_count + 1)  # 多取一根，排除当前未完成的
        )
        result = await db.execute(query)
        klines = result.scalars().all()
        
        if len(klines) < confirm_count:
            logger.debug(f"[ConditionalMonitor] Not enough klines for confirmation")
            return False
        
        # 跳过第一根 (可能未完成)，检查后续的
        confirmed_count = 0
        for kline in klines[1:confirm_count+1]:
            if trade_side == TradeSide.LONG:
                # 做多: K 线收盘价需要高于触发价
                if kline.close > trigger_price:
                    confirmed_count += 1
            else:
                # 做空: K 线收盘价需要低于触发价
                if kline.close < trigger_price:
                    confirmed_count += 1
        
        return confirmed_count >= confirm_count
    
    @classmethod
    async def execute_task(
        cls,
        db: AsyncSession,
        task_id: int,
    ) -> bool:
        """
        执行条件任务 (市价单 + 止损止盈)
        
        Args:
            db: 数据库会话
            task_id: 任务ID
            
        Returns:
            是否执行成功
        """
        task = await db.get(TaskTicket, task_id)
        if not task:
            return False
        
        try:
            task.status = TaskStatus.EXECUTING
            await db.commit()
            
            # 确定订单方向
            order_side = OrderSide.BUY if task.trade_side == TradeSide.LONG else OrderSide.SELL
            
            # 创建市价单
            order = await OrderExecutor.create_order(
                db=db,
                user_id=task.user_id,
                symbol=task.symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=task.quantity,
                leverage=task.leverage or 5,
                stop_loss=task.stop_loss,
                take_profit=task.take_profit,
                note=f"Right-side breakout task #{task.id}",
            )
            
            # 更新任务状态
            task.status = TaskStatus.COMPLETED
            task.executed_at = utc_now()
            task.execution_result = {
                "order_id": order.id,
                "executed_price": str(order.avg_price) if order.avg_price else None,
                "executed_at": utc_now().isoformat(),
            }
            await db.commit()
            
            logger.info(f"[ConditionalMonitor] Task {task_id} executed successfully, order {order.id}")
            return True
            
        except Exception as e:
            logger.error(f"[ConditionalMonitor] Failed to execute task {task_id}: {e}")
            task.status = TaskStatus.FAILED
            task.execution_result = {"error": str(e)}
            await db.commit()
            return False
    
    @classmethod
    async def cancel_task(
        cls,
        db: AsyncSession,
        task_id: int,
    ) -> bool:
        """
        取消条件任务
        
        Args:
            db: 数据库会话
            task_id: 任务ID
            
        Returns:
            是否取消成功
        """
        task = await db.get(TaskTicket, task_id)
        if not task:
            return False
        
        if task.status not in (TaskStatus.MONITORING, TaskStatus.PENDING):
            logger.warning(f"[ConditionalMonitor] Cannot cancel task {task_id} with status {task.status}")
            return False
        
        task.status = TaskStatus.CANCELLED
        await db.commit()
        
        logger.info(f"[ConditionalMonitor] Task {task_id} cancelled")
        return True
    
    @classmethod
    async def get_monitoring_tasks(
        cls,
        db: AsyncSession,
        user_id: Optional[int] = None,
    ) -> list[TaskTicket]:
        """
        获取所有监控中的任务
        
        Args:
            db: 数据库会话
            user_id: 可选，过滤特定用户
            
        Returns:
            监控中的任务列表
        """
        query = select(TaskTicket).where(TaskTicket.status == TaskStatus.MONITORING)
        
        if user_id:
            query = query.where(TaskTicket.user_id == user_id)
        
        result = await db.execute(query)
        return list(result.scalars().all())
