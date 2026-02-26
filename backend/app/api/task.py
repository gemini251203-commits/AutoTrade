"""
Task API
=========
AI 任务单相关端点
"""

from decimal import Decimal
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.deps import get_db, get_current_user, DbSession, CurrentUser
from app.models.user import User
from app.models.task import (
from app.core.time_utils import utc_now
    TaskTicket, TaskSource, TaskType, TaskStatus,
    TradingMode, TradeSide, ConfirmInterval, ConditionType
)


router = APIRouter()


# ==================== Schemas ====================

class TaskCreate(BaseModel):
    symbol: str
    task_type: TaskType
    side: str  # buy/sell
    quantity: Decimal
    
    # 左侧/右侧交易
    trading_mode: TradingMode = TradingMode.MARKET
    trade_side: Optional[TradeSide] = None  # long/short
    
    # 左侧交易: 入场价格
    entry_low: Optional[Decimal] = None
    entry_high: Optional[Decimal] = None
    
    # 右侧交易: 突破条件
    trigger_price: Optional[Decimal] = None
    max_deviation_pct: Decimal = Decimal("0.5")
    confirm_interval: ConfirmInterval = ConfirmInterval.M15
    confirm_count: int = 1  # 假突破防护
    timeout_hours: int = 24  # 超时时间
    
    # 🔥 两阶段条件类型
    condition_type: ConditionType = ConditionType.SIMPLE_BREAKOUT
    
    # 止盈止损
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    leverage: int = 5
    
    note: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    source: TaskSource
    task_type: TaskType
    status: TaskStatus
    symbol: str
    side: str
    quantity: Decimal
    
    # 左侧/右侧交易
    trading_mode: Optional[TradingMode] = None
    trade_side: Optional[TradeSide] = None
    
    # 价格参数
    entry_low: Optional[Decimal] = None
    entry_high: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    max_deviation_pct: Optional[Decimal] = None
    confirm_interval: Optional[ConfirmInterval] = None
    confirm_count: Optional[int] = None
    timeout_hours: Optional[int] = None
    expires_at: Optional[datetime] = None
    
    # 🔥 两阶段条件参数
    condition_type: Optional[ConditionType] = None
    condition_phase: Optional[int] = None
    
    # 止盈止损
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    leverage: Optional[int] = None
    
    confidence: Optional[float] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ==================== Routes ====================

@router.get("/", response_model=List[TaskResponse])
async def list_tasks(
    status_filter: Optional[TaskStatus] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取任务单列表"""
    query = select(TaskTicket).where(TaskTicket.user_id == current_user.id)
    
    if status_filter:
        query = query.where(TaskTicket.status == status_filter)
    
    query = query.order_by(TaskTicket.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/", response_model=TaskResponse)
async def create_task(
    task_in: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建任务单
    
    支持三种模式:
    - MARKET: 即时市价单
    - LEFT_SIDE: 左侧限价挂单
    - RIGHT_SIDE: 右侧条件单 (突破后执行)
    """
    from loguru import logger
    
    try:
        # 计算过期时间 (右侧条件单)
        expires_at = None
        if task_in.trading_mode == TradingMode.RIGHT_SIDE:
            expires_at = utc_now() + timedelta(hours=task_in.timeout_hours)
        
        # 创建任务
        task = TaskTicket(
            user_id=current_user.id,
            source=TaskSource.USER,
            task_type=task_in.task_type,
            symbol=task_in.symbol.upper(),
            side=task_in.side,
            quantity=task_in.quantity,
            
            # 左侧/右侧交易
            trading_mode=task_in.trading_mode,
            trade_side=task_in.trade_side,
            
            # 价格参数
            entry_low=task_in.entry_low,
            entry_high=task_in.entry_high,
            trigger_price=task_in.trigger_price,
            max_deviation_pct=task_in.max_deviation_pct,
            confirm_interval=task_in.confirm_interval,
            confirm_count=task_in.confirm_count,
            timeout_hours=task_in.timeout_hours,
            expires_at=expires_at,
            
            # 止盈止损
            stop_loss=task_in.stop_loss,
            take_profit=task_in.take_profit,
            leverage=task_in.leverage,
            
            note=task_in.note,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        
        logger.info(f"[Task] Created task {task.id}: mode={task.trading_mode.value if task.trading_mode else 'None'} side={task.trade_side.value if task.trade_side else task.side}")
        return task
    
    except Exception as e:
        logger.error(f"[Task] Failed to create task: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )


@router.post("/{task_id}/approve", response_model=TaskResponse)
async def approve_task(
    task_id: int,
    auto_execute: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    审批任务单
    
    根据 trading_mode 执行不同逻辑:
    - MARKET: 立即市价执行
    - LEFT_SIDE: 创建限价单
    - RIGHT_SIDE: 开始条件监控
    """
    from app.services.trading.order_executor import OrderExecutor
    from app.services.trading.conditional_order import ConditionalOrderMonitor
    from app.models.order import OrderSide, OrderType
    from loguru import logger
    
    result = await db.execute(
        select(TaskTicket).where(
            TaskTicket.id == task_id,
            TaskTicket.user_id == current_user.id,
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task cannot be approved (status: {task.status.value})",
        )
    
    task.status = TaskStatus.APPROVED
    task.approved_at = utc_now()
    await db.commit()
    
    if auto_execute:
        trading_mode = task.trading_mode or TradingMode.MARKET
        
        if trading_mode == TradingMode.LEFT_SIDE:
            # 左侧交易: 创建限价单
            logger.info(f"[Task] Creating limit order for left-side task {task_id}")
            entry_price = task.entry_low or task.entry_high
            if not entry_price:
                task.status = TaskStatus.FAILED
                task.execution_result = {"error": "No entry price specified"}
                await db.commit()
            else:
                try:
                    order_side = OrderSide.BUY if task.trade_side == TradeSide.LONG else OrderSide.SELL
                    
                    # 🔥 修复: task.quantity 是保证金 (USDT)，需转换为合约数量
                    # 公式: 合约数量 = (保证金 × 杠杆) / 入场价格
                    margin = task.quantity  # 保证金 (USDT)
                    leverage = task.leverage or 5
                    contract_quantity = (margin * Decimal(leverage)) / entry_price
                    
                    logger.info(f"[Task] Margin={margin} USDT, Leverage={leverage}x, Entry={entry_price}")
                    logger.info(f"[Task] Contract quantity calculated: {contract_quantity}")
                    
                    order = await OrderExecutor.create_order(
                        db=db,
                        user_id=task.user_id,
                        symbol=task.symbol,
                        side=order_side,
                        order_type=OrderType.LIMIT,
                        quantity=contract_quantity,  # 使用计算后的合约数量
                        price=entry_price,
                        leverage=leverage,
                        stop_loss=task.stop_loss,
                        take_profit=task.take_profit,
                        note=f"Left-side task #{task.id}",
                    )
                    task.status = TaskStatus.EXECUTING  # 等待成交
                    task.execution_result = {"order_id": order.id, "contract_qty": str(contract_quantity)}
                    await db.commit()
                    logger.info(f"[Task] Limit order {order.id} created")
                except Exception as e:
                    logger.error(f"[Task] Failed to create limit order: {e}")
                    task.status = TaskStatus.FAILED
                    task.execution_result = {"error": str(e)}
                    await db.commit()
        
        elif trading_mode == TradingMode.RIGHT_SIDE:
            # 右侧交易: 开始条件监控
            logger.info(f"[Task] Starting condition monitoring for task {task_id}")
            await ConditionalOrderMonitor.start_monitoring(db, task_id)
        
        else:
            # 市价单: 立即执行
            from app.services.task import TaskExecutor
            logger.info(f"[Task] Executing market order for task {task_id}")
            exec_result = await TaskExecutor.execute(db, task)
            if not exec_result.success:
                logger.warning(f"[Task] Execution failed: {exec_result.message}")
    
    await db.refresh(task)
    return task


@router.post("/{task_id}/reject", response_model=TaskResponse)
async def reject_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """拒绝任务单"""
    result = await db.execute(
        select(TaskTicket).where(
            TaskTicket.id == task_id,
            TaskTicket.user_id == current_user.id,
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task cannot be rejected (status: {task.status.value})",
        )
    
    task.status = TaskStatus.REJECTED
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    取消任务单
    
    可取消状态: PENDING, MONITORING
    """
    from app.services.trading.conditional_order import ConditionalOrderMonitor
    
    result = await db.execute(
        select(TaskTicket).where(
            TaskTicket.id == task_id,
            TaskTicket.user_id == current_user.id,
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    
    if task.status not in (TaskStatus.PENDING, TaskStatus.MONITORING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task cannot be cancelled (status: {task.status.value})",
        )
    
    # 使用监控器取消
    if task.status == TaskStatus.MONITORING:
        await ConditionalOrderMonitor.cancel_task(db, task_id)
    else:
        task.status = TaskStatus.CANCELLED
        await db.commit()
    
    await db.refresh(task)
    return task
