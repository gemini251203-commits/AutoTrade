"""
Grid Trading API
=================
网格交易端点

端点:
    GET  /api/grid/            - 获取用户网格机器人列表
    POST /api/grid/            - 创建网格机器人
    POST /api/grid/{id}/start  - 启动网格
    POST /api/grid/{id}/stop   - 停止网格
    GET  /api/grid/{id}        - 获取网格详情
"""

from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.grid_bot import GridBot, GridType, GridStatus, GridDirection
from app.services.grid import GridStrategy, GridError


router = APIRouter(tags=["Grid"])


# ==================== Schemas ====================

class GridCreateRequest(BaseModel):
    """创建网格请求"""
    name: str = Field(..., min_length=1, max_length=100, example="BTC 网格 #1")
    symbol: str = Field(..., example="BTCUSDT")
    lower_price: Decimal = Field(..., gt=0, example=70000)
    upper_price: Decimal = Field(..., gt=0, example=90000)
    grid_count: int = Field(..., ge=2, le=200, example=20)
    investment: Decimal = Field(..., gt=0, example=1000)
    leverage: int = Field(default=1, ge=1, le=125, example=5)
    grid_type: GridType = Field(default=GridType.ARITHMETIC)
    direction: GridDirection = Field(default=GridDirection.LONG)
    stop_loss_price: Optional[Decimal] = Field(default=None, example=65000)
    take_profit_price: Optional[Decimal] = Field(default=None, example=95000)


class GridStartRequest(BaseModel):
    """启动网格请求"""
    current_price: Decimal = Field(..., gt=0, example=79000)


class GridResponse(BaseModel):
    """网格响应"""
    id: int
    name: str
    symbol: str
    grid_type: GridType
    direction: GridDirection
    status: GridStatus
    upper_price: str
    lower_price: str
    grid_count: int
    investment: str
    leverage: int
    grid_interval: Optional[str]
    quantity_per_grid: Optional[str]
    current_level: int
    filled_buy_count: int
    filled_sell_count: int
    total_profit: str
    realized_pnl: str
    profit_rate: str
    created_at: str
    started_at: Optional[str]


class GridDetailResponse(GridResponse):
    """网格详情响应 (含级别数据)"""
    grid_levels: Optional[List[dict]]


# ==================== Helper ====================

def bot_to_response(bot: GridBot) -> GridResponse:
    """转换 GridBot 为 API 响应"""
    return GridResponse(
        id=bot.id,
        name=bot.name,
        symbol=bot.symbol,
        grid_type=bot.grid_type,
        direction=bot.direction,
        status=bot.status,
        upper_price=str(bot.upper_price),
        lower_price=str(bot.lower_price),
        grid_count=bot.grid_count,
        investment=str(bot.investment),
        leverage=bot.leverage,
        grid_interval=str(bot.grid_interval) if bot.grid_interval else None,
        quantity_per_grid=str(bot.quantity_per_grid) if bot.quantity_per_grid else None,
        current_level=bot.current_level,
        filled_buy_count=bot.filled_buy_count,
        filled_sell_count=bot.filled_sell_count,
        total_profit=str(bot.total_profit.quantize(Decimal("0.01"))),
        realized_pnl=str(bot.realized_pnl.quantize(Decimal("0.01"))),
        profit_rate=str(bot.profit_rate.quantize(Decimal("0.01"))),
        created_at=bot.created_at.isoformat(),
        started_at=bot.started_at.isoformat() if bot.started_at else None,
    )


# ==================== Routes ====================

@router.get("/", response_model=List[GridResponse])
async def list_grid_bots(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[GridStatus] = None,
):
    """获取用户网格机器人列表"""
    bots = await GridStrategy.get_user_grid_bots(db, current_user.id, status_filter)
    return [bot_to_response(bot) for bot in bots]


@router.post("/", response_model=GridResponse)
async def create_grid_bot(
    request: GridCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    创建网格机器人
    
    参数:
    - name: 机器人名称
    - symbol: 交易对 (如 BTCUSDT)
    - lower_price / upper_price: 网格价格区间
    - grid_count: 网格数量 (2-200)
    - investment: 投入金额 (USDT)
    - leverage: 杠杆倍数
    - grid_type: arithmetic (等差) 或 geometric (等比)
    - direction: long (做多) 或 short (做空) 或 neutral (中性)
    """
    try:
        # 直接调用服务方法 (session 已经在隐式事务中)
        bot = await GridStrategy.create_grid_bot(
            db=db,
            user_id=current_user.id,
            name=request.name,
            symbol=request.symbol,
            lower_price=request.lower_price,
            upper_price=request.upper_price,
            grid_count=request.grid_count,
            investment=request.investment,
            leverage=request.leverage,
            grid_type=request.grid_type,
            direction=request.direction,
            stop_loss_price=request.stop_loss_price,
            take_profit_price=request.take_profit_price,
        )
        
        # 提交事务
        await db.commit()
        
        # 刷新实例以获取最新数据
        await db.refresh(bot)
        return bot_to_response(bot)
        
    except GridError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"[GridAPI] create_grid_bot failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/{bot_id}/start", response_model=GridResponse)
async def start_grid_bot(
    bot_id: int,
    request: GridStartRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    启动网格机器人
    
    根据当前价格在网格区间内放置订单
    """
    try:
        bot = await GridStrategy.start_grid(
            db=db,
            bot_id=bot_id,
            current_price=request.current_price,
        )
        
        await db.commit()
        await db.refresh(bot)
        return bot_to_response(bot)
        
    except GridError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"[GridAPI] start_grid_bot failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/{bot_id}/stop", response_model=GridResponse)
async def stop_grid_bot(
    bot_id: int,
    current_user: CurrentUser,
    db: DbSession,
    cancel_orders: bool = True,
):
    """
    停止网格机器人
    
    取消所有挂单并释放资金
    """
    try:
        bot = await GridStrategy.stop_grid(
            db=db,
            bot_id=bot_id,
            cancel_orders=cancel_orders,
        )
        
        await db.commit()
        await db.refresh(bot)
        return bot_to_response(bot)
        
    except GridError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"[GridAPI] stop_grid_bot failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{bot_id}", response_model=GridDetailResponse)
async def get_grid_bot(
    bot_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """获取网格机器人详情"""
    result = await db.execute(
        select(GridBot).where(
            GridBot.id == bot_id,
            GridBot.user_id == current_user.id,
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grid bot not found",
        )
    
    response = bot_to_response(bot)
    return GridDetailResponse(
        **response.model_dump(),
        grid_levels=bot.grid_levels,
    )


@router.delete("/{bot_id}")
async def delete_grid_bot(
    bot_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    删除网格机器人
    
    只能删除已停止的网格
    """
    result = await db.execute(
        select(GridBot).where(
            GridBot.id == bot_id,
            GridBot.user_id == current_user.id,
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grid bot not found",
        )
    
    # 只能删除已停止或已创建的网格
    if bot.status not in (GridStatus.STOPPED, GridStatus.CREATED, GridStatus.COMPLETED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete running grid bot. Stop it first.",
        )
    
    await db.delete(bot)
    await db.commit()
    
    return {"message": f"Grid bot #{bot_id} deleted"}
