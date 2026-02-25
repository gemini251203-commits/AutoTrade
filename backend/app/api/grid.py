"""
Grid Trading API
=================
缃戞牸浜ゆ槗绔偣

绔偣:
    GET  /api/grid/            - 鑾峰彇鐢ㄦ埛缃戞牸鏈哄櫒浜哄垪琛?
    POST /api/grid/            - 鍒涘缓缃戞牸鏈哄櫒浜?
    POST /api/grid/{id}/start  - 鍚姩缃戞牸
    POST /api/grid/{id}/stop   - 鍋滄缃戞牸
    GET  /api/grid/{id}        - 鑾峰彇缃戞牸璇︽儏
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
    """鍒涘缓缃戞牸璇锋眰"""
    name: str = Field(..., min_length=1, max_length=100, example="BTC 缃戞牸 #1")
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
    """鍚姩缃戞牸璇锋眰"""
    current_price: Decimal = Field(..., gt=0, example=79000)


class GridResponse(BaseModel):
    """缃戞牸鍝嶅簲"""
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
    total_commission: str
    realized_pnl: str
    profit_rate: str
    matched_count: int
    created_at: str
    started_at: Optional[str]


class GridDetailResponse(GridResponse):
    """缃戞牸璇︽儏鍝嶅簲 (鍚骇鍒暟鎹?"""
    grid_levels: Optional[List[dict]]


# ==================== Helper ====================

def bot_to_response(bot: GridBot) -> GridResponse:
    """杞崲 GridBot 涓?API 鍝嶅簲"""
    # 鏍煎紡鍖栧皬鏁颁綅: 浠锋牸2浣? 鏁伴噺5浣? 閲戦2浣?
    def fmt_price(v: Decimal) -> str:
        return str(v.quantize(Decimal("0.01")))
    
    def fmt_qty(v: Decimal) -> str:
        return str(v.quantize(Decimal("0.00001")))
    
    return GridResponse(
        id=bot.id,
        name=bot.name,
        symbol=bot.symbol,
        grid_type=bot.grid_type,
        direction=bot.direction,
        status=bot.status,
        upper_price=fmt_price(bot.upper_price),
        lower_price=fmt_price(bot.lower_price),
        grid_count=bot.grid_count,
        investment=fmt_price(bot.investment),
        leverage=bot.leverage,
        grid_interval=fmt_price(bot.grid_interval) if bot.grid_interval else None,
        quantity_per_grid=fmt_qty(bot.quantity_per_grid) if bot.quantity_per_grid else None,
        current_level=bot.current_level,
        filled_buy_count=bot.filled_buy_count,
        filled_sell_count=bot.filled_sell_count,
        total_profit=fmt_price(bot.total_profit),
        total_commission=fmt_price(bot.total_commission),
        realized_pnl=fmt_price(bot.realized_pnl),
        profit_rate=fmt_price(bot.profit_rate),
        matched_count=bot.matched_count,
        created_at=bot.created_at.isoformat() + "Z",
        started_at=bot.started_at.isoformat() + "Z" if bot.started_at else None,
    )


# ==================== Routes ====================

@router.get("/", response_model=List[GridResponse])
async def list_grid_bots(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[GridStatus] = None,
):
    """鑾峰彇鐢ㄦ埛缃戞牸鏈哄櫒浜哄垪琛?""
    bots = await GridStrategy.get_user_grid_bots(db, current_user.id, status_filter)
    return [bot_to_response(bot) for bot in bots]


@router.post("/", response_model=GridResponse)
async def create_grid_bot(
    request: GridCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    鍒涘缓缃戞牸鏈哄櫒浜?
    
    鍙傛暟:
    - name: 鏈哄櫒浜哄悕绉?
    - symbol: 浜ゆ槗瀵?(濡?BTCUSDT)
    - lower_price / upper_price: 缃戞牸浠锋牸鍖洪棿
    - grid_count: 缃戞牸鏁伴噺 (2-200)
    - investment: 鎶曞叆閲戦 (USDT)
    - leverage: 鏉犳潌鍊嶆暟
    - grid_type: arithmetic (绛夊樊) 鎴?geometric (绛夋瘮)
    - direction: long (鍋氬) 鎴?short (鍋氱┖) 鎴?neutral (涓€?
    """
    try:
        # 鐩存帴璋冪敤鏈嶅姟鏂规硶 (session 宸茬粡鍦ㄩ殣寮忎簨鍔′腑)
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
        
        # 鎻愪氦浜嬪姟
        await db.commit()
        
        # 鍒锋柊瀹炰緥浠ヨ幏鍙栨渶鏂版暟鎹?
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
    鍚姩缃戞牸鏈哄櫒浜?
    
    鏍规嵁褰撳墠浠锋牸鍦ㄧ綉鏍煎尯闂村唴鏀剧疆璁㈠崟
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
    鍋滄缃戞牸鏈哄櫒浜?
    
    鍙栨秷鎵€鏈夋寕鍗曞苟閲婃斁璧勯噾
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
    """鑾峰彇缃戞牸鏈哄櫒浜鸿鎯?""
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
    鍒犻櫎缃戞牸鏈哄櫒浜?
    
    鍙兘鍒犻櫎宸插仠姝㈢殑缃戞牸
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
    
    # 鍙兘鍒犻櫎宸插仠姝㈡垨宸插垱寤虹殑缃戞牸
    if bot.status not in (GridStatus.STOPPED, GridStatus.CREATED, GridStatus.COMPLETED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete running grid bot. Stop it first.",
        )
    
    await db.delete(bot)
    await db.commit()
    
    return {"message": f"Grid bot #{bot_id} deleted"}
