"""
Task Executor
==============
任务执行引擎

负责执行已审批的任务单，分发到不同的交易服务
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.task import TaskTicket, TaskType, TaskStatus
from app.models.position import PositionSide
from app.models.order import OrderSide, OrderType
from app.services.trading import PositionManager, OrderExecutor
from app.services.grid import GridStrategy
from app.core.time_utils import utc_now


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    message: str
    order_ids: list = None
    position_id: Optional[int] = None
    grid_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


class TaskExecutor:
    """
    任务执行器
    
    根据任务类型分发到不同的执行器:
    - BUY/SELL → OrderExecutor
    - CLOSE → PositionManager
    - GRID → GridStrategy
    """
    
    @staticmethod
    async def execute(
        db: AsyncSession,
        task: TaskTicket,
    ) -> ExecutionResult:
        """
        执行任务
        
        Args:
            db: 数据库会话
            task: 已审批的任务单
            
        Returns:
            执行结果
        """
        if task.status != TaskStatus.APPROVED:
            return ExecutionResult(
                success=False,
                message=f"任务状态不是 APPROVED，当前: {task.status.value}",
            )
        
        # 更新状态为执行中
        task.status = TaskStatus.EXECUTING
        await db.commit()
        
        try:
            # 根据任务类型分发
            if task.task_type == TaskType.BUY:
                result = await TaskExecutor._execute_buy(db, task)
            elif task.task_type == TaskType.SELL:
                result = await TaskExecutor._execute_sell(db, task)
            elif task.task_type == TaskType.CLOSE:
                result = await TaskExecutor._execute_close(db, task)
            elif task.task_type == TaskType.ADJUST:
                result = await TaskExecutor._execute_adjust(db, task)
            else:
                result = ExecutionResult(
                    success=False,
                    message=f"不支持的任务类型: {task.task_type.value}",
                )
            
            # 更新任务状态
            if result.success:
                task.status = TaskStatus.COMPLETED
                task.executed_at = utc_now()
                task.execution_result = {
                    "success": True,
                    "message": result.message,
                    "order_ids": result.order_ids,
                    "position_id": result.position_id,
                    "details": result.details,
                }
            else:
                task.status = TaskStatus.FAILED
                task.execution_result = {
                    "success": False,
                    "message": result.message,
                }
            
            await db.commit()
            return result
            
        except Exception as e:
            logger.error(f"[TaskExecutor] Execution failed: {e}")
            task.status = TaskStatus.FAILED
            task.execution_result = {"success": False, "message": str(e)}
            await db.commit()
            return ExecutionResult(success=False, message=str(e))
    
    @staticmethod
    async def _execute_buy(
        db: AsyncSession,
        task: TaskTicket,
    ) -> ExecutionResult:
        """执行买入任务"""
        try:
            # 获取入场价格：优先使用任务中的价格，否则获取实时价格
            entry_price = task.entry_low or task.entry_high
            
            if not entry_price or entry_price <= 0:
                # 获取实时价格
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(
                            f"https://fapi.binance.com/fapi/v1/ticker/price",
                            params={"symbol": task.symbol}
                        )
                        if resp.status_code == 200:
                            entry_price = Decimal(str(resp.json()["price"]))
                        else:
                            return ExecutionResult(success=False, message="无法获取实时价格")
                except Exception as e:
                    logger.error(f"[TaskExecutor] Failed to fetch price: {e}")
                    return ExecutionResult(success=False, message=f"获取价格失败: {e}")
            
            # 使用任务中的杠杆，默认 10x
            leverage = task.leverage or 10
            
            async with db.begin_nested():
                position = await PositionManager.open_position(
                    db=db,
                    user_id=task.user_id,
                    symbol=task.symbol,
                    side=PositionSide.LONG,
                    quantity=task.quantity,
                    entry_price=entry_price,
                    leverage=leverage,
                    stop_loss=task.stop_loss,
                    take_profit=task.take_profit,
                )
            
            logger.info(f"[TaskExecutor] Buy executed: {task.symbol} qty={task.quantity} @ {entry_price}")
            
            return ExecutionResult(
                success=True,
                message=f"买入成功: {task.symbol} @ {entry_price}",
                position_id=position.id if position else None,
            )
        
        except Exception as e:
            logger.error(f"[TaskExecutor] Buy failed: {e}")
            return ExecutionResult(success=False, message=str(e))
    
    @staticmethod
    async def _execute_sell(
        db: AsyncSession,
        task: TaskTicket,
    ) -> ExecutionResult:
        """执行卖出任务 (开空)"""
        try:
            # 获取入场价格
            entry_price = task.entry_low or task.entry_high
            
            if not entry_price or entry_price <= 0:
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(
                            f"https://fapi.binance.com/fapi/v1/ticker/price",
                            params={"symbol": task.symbol}
                        )
                        if resp.status_code == 200:
                            entry_price = Decimal(str(resp.json()["price"]))
                        else:
                            return ExecutionResult(success=False, message="无法获取实时价格")
                except Exception as e:
                    logger.error(f"[TaskExecutor] Failed to fetch price: {e}")
                    return ExecutionResult(success=False, message=f"获取价格失败: {e}")
            
            leverage = task.leverage or 10
            
            async with db.begin_nested():
                position = await PositionManager.open_position(
                    db=db,
                    user_id=task.user_id,
                    symbol=task.symbol,
                    side=PositionSide.SHORT,
                    quantity=task.quantity,
                    entry_price=entry_price,
                    leverage=leverage,
                    stop_loss=task.stop_loss,
                    take_profit=task.take_profit,
                )
            
            logger.info(f"[TaskExecutor] Sell executed: {task.symbol} qty={task.quantity} @ {entry_price}")
            
            return ExecutionResult(
                success=True,
                message=f"做空成功: {task.symbol} @ {entry_price}",
                position_id=position.id if position else None,
            )
        
        except Exception as e:
            logger.error(f"[TaskExecutor] Sell failed: {e}")
            return ExecutionResult(success=False, message=str(e))
    
    @staticmethod
    async def _execute_close(
        db: AsyncSession,
        task: TaskTicket,
    ) -> ExecutionResult:
        """执行平仓任务"""
        try:
            # 查找对应持仓并平仓
            from app.models.position import Position, PositionStatus
            
            # 根据 symbol 和方向查找持仓
            side = PositionSide.LONG if task.side == "long" else PositionSide.SHORT
            
            result = await db.execute(
                select(Position).where(
                    Position.user_id == task.user_id,
                    Position.symbol == task.symbol,
                    Position.side == side,
                    Position.status == PositionStatus.OPEN,
                )
            )
            position = result.scalar_one_or_none()
            
            if not position:
                return ExecutionResult(
                    success=False,
                    message=f"未找到 {task.symbol} {task.side} 持仓",
                )
            
            async with db.begin_nested():
                await PositionManager.close_position(
                    db=db,
                    position_id=position.id,
                    close_price=task.entry_low or position.entry_price,
                )
            
            logger.info(f"[TaskExecutor] Close executed: {task.symbol}")
            
            return ExecutionResult(
                success=True,
                message=f"平仓成功: {task.symbol}",
                position_id=position.id,
            )
        
        except Exception as e:
            logger.error(f"[TaskExecutor] Close failed: {e}")
            return ExecutionResult(success=False, message=str(e))
    
    @staticmethod
    async def _execute_adjust(
        db: AsyncSession,
        task: TaskTicket,
    ) -> ExecutionResult:
        """执行调整任务 (如修改止盈止损)"""
        try:
            from app.models.position import Position, PositionStatus
            
            side = PositionSide.LONG if task.side == "long" else PositionSide.SHORT
            
            result = await db.execute(
                select(Position).where(
                    Position.user_id == task.user_id,
                    Position.symbol == task.symbol,
                    Position.side == side,
                    Position.status == PositionStatus.OPEN,
                )
            )
            position = result.scalar_one_or_none()
            
            if not position:
                return ExecutionResult(
                    success=False,
                    message=f"未找到 {task.symbol} {task.side} 持仓",
                )
            
            # 更新止盈止损
            if task.stop_loss:
                position.stop_loss = task.stop_loss
            if task.take_profit:
                position.take_profit = task.take_profit
            
            await db.commit()
            
            logger.info(f"[TaskExecutor] Adjust executed: {task.symbol} SL={task.stop_loss} TP={task.take_profit}")
            
            return ExecutionResult(
                success=True,
                message=f"调整成功: {task.symbol}",
                position_id=position.id,
                details={
                    "stop_loss": str(task.stop_loss) if task.stop_loss else None,
                    "take_profit": str(task.take_profit) if task.take_profit else None,
                },
            )
        
        except Exception as e:
            logger.error(f"[TaskExecutor] Adjust failed: {e}")
            return ExecutionResult(success=False, message=str(e))
