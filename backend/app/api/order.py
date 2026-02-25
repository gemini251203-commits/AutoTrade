"""
Order API (鍚堢害浜ゆ槗鐗?
=======================
璁㈠崟绠＄悊绔偣

绔偣:
    GET  /api/order/              - 鑾峰彇鐢ㄦ埛璁㈠崟鍒楄〃
    POST /api/order/              - 鍒涘缓璁㈠崟
    POST /api/order/{id}/cancel   - 鍙栨秷璁㈠崟
    GET  /api/order/{id}          - 鑾峰彇璁㈠崟璇︽儏
"""

from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.order import Order, OrderSide, OrderType, OrderStatus
from app.models.position import PositionSide
from app.services.trading import OrderExecutor, OrderError, OrderNotFoundError


router = APIRouter(tags=["Order"])


# ==================== Schemas ====================

class OrderCreateRequest(BaseModel):
    """鍒涘缓璁㈠崟璇锋眰"""
    symbol: str = Field(..., example="BTCUSDT")
    side: OrderSide = Field(..., example="buy")
    order_type: OrderType = Field(..., example="market")
    quantity: Decimal = Field(..., gt=0, example=0.01)
    price: Optional[Decimal] = Field(default=None, example=79000)
    trigger_price: Optional[Decimal] = Field(default=None, example=75000)
    leverage: int = Field(default=10, ge=1, le=125, example=10)
    position_side: Optional[PositionSide] = Field(default=None)
    reduce_only: bool = Field(default=False)
    stop_loss: Optional[Decimal] = Field(default=None)
    take_profit: Optional[Decimal] = Field(default=None)
    note: Optional[str] = Field(default=None)


class OrderResponse(BaseModel):
    """璁㈠崟鍝嶅簲"""
    model_config = {"from_attributes": True, "json_encoders": {Decimal: str}}

    id: int
    user_id: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    leverage: int
    position_side: Optional[PositionSide]
    reduce_only: bool
    quantity: Decimal
    filled_quantity: Decimal
    price: Optional[Decimal]
    trigger_price: Optional[Decimal]
    avg_fill_price: Optional[Decimal]
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    commission: Decimal
    realized_pnl: Decimal
    created_at: str
    filled_at: Optional[str]


# ==================== Routes ====================

@router.get("/", response_model=List[OrderResponse])
async def list_orders(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[OrderStatus] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
):
    """
    鑾峰彇鐢ㄦ埛璁㈠崟鍒楄〃
    
    鍙€夎繃婊ゆ潯浠?
    - status_filter: pending, open, filled, cancelled
    - symbol: BTCUSDT 绛?
    """
    orders = await OrderExecutor.get_user_orders(
        db, current_user.id, status_filter, symbol, limit
    )
    
    return [
        OrderResponse(
            id=o.id,
            user_id=o.user_id,
            symbol=o.symbol,
            side=o.side,
            order_type=o.order_type,
            status=o.status,
            leverage=o.leverage,
            position_side=o.position_side,
            reduce_only=o.reduce_only,
            quantity=o.quantity,
            filled_quantity=o.filled_quantity,
            price=o.price,
            trigger_price=o.trigger_price,
            avg_fill_price=o.avg_fill_price,
            stop_loss=o.stop_loss,
            take_profit=o.take_profit,
            commission=o.commission,
            realized_pnl=o.realized_pnl,
            created_at=o.created_at.isoformat() + "Z",
            filled_at=o.filled_at.isoformat() + "Z" if o.filled_at else None,
        )
        for o in orders
    ]


@router.post("/", response_model=OrderResponse)
async def create_order(
    request: OrderCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    鍒涘缓璁㈠崟 (閫氳繃缁熶竴 Pipeline)
    
    璁㈠崟绫诲瀷:
    - market: 甯備环鍗?(绔嬪嵆鎴愪氦)
    - limit: 闄愪环鍗?(鎸傚崟绛夊緟)
    - stop_market: 姝㈡崯甯備环鍗?(闇€瑕?trigger_price)
    - stop_limit: 姝㈡崯闄愪环鍗?(闇€瑕?trigger_price + price)
    - take_profit_market: 姝㈢泩甯備环鍗?
    - take_profit_limit: 姝㈢泩闄愪环鍗?
    
    鈿狅笍 鎵€鏈夎鍗曢€氳繃 Pipeline 缁熶竴鍏ュ彛: Risk 瀹℃壒 鈫?Execution 鎵ц
    """
    from app.core.pipeline import get_pipeline
    from sqlalchemy import select
    from app.models.wallet import Wallet
    from app.models.position import Position, PositionStatus
    
    try:
        pipeline = get_pipeline(current_user.id)
        
        # 鑾峰彇浣欓鍜屾寔浠撶敤浜庨鎺?
        wallet_result = await db.execute(
            select(Wallet).where(Wallet.user_id == current_user.id)
        )
        wallet = wallet_result.scalar_one_or_none()
        
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == current_user.id,
                Position.status == PositionStatus.OPEN,
            )
        )
        positions = pos_result.scalars().all()
        open_positions = [
            {"symbol": p.symbol, "side": p.side.value, "size": float(p.size)}
            for p in positions
        ]
        
        result = await pipeline.submit_order(
            db=db,
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            leverage=request.leverage,
            order_type=request.order_type.value,
            price=request.price,
            trigger_price=request.trigger_price,
            position_side=request.position_side.value if request.position_side else None,
            reduce_only=request.reduce_only,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            source="manual",
            note=request.note or "",
            available_balance=Decimal(str(wallet.balance)) if wallet else Decimal("0"),
            total_equity=Decimal(str(wallet.total_equity)) if wallet else Decimal("0"),
            open_positions=open_positions,
        )
        
        if not result.get("success"):
            raise OrderError(result.get("error", "Pipeline 鎵ц澶辫触"))
        
        # 浠?DB 鍔犺浇瀹屾暣 order 瀵硅薄浠ユ瀯閫犲搷搴?
        order_id = result.get("order_id")
        order = await db.get(Order, order_id)
        
        await db.commit()
        await db.refresh(order)
        
        return OrderResponse(
            id=order.id,
            user_id=order.user_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            status=order.status,
            leverage=order.leverage,
            position_side=order.position_side,
            reduce_only=order.reduce_only,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            price=order.price,
            trigger_price=order.trigger_price,
            avg_fill_price=order.avg_fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            commission=order.commission,
            realized_pnl=order.realized_pnl,
            created_at=order.created_at.isoformat() + "Z",
            filled_at=order.filled_at.isoformat() + "Z" if order.filled_at else None,
        )
        
    except OrderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )



@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    鍙栨秷璁㈠崟
    
    鍙湁娲昏穬璁㈠崟 (pending/open/partial) 鍙互鍙栨秷
    鍙栨秷鍚庝細閲婃斁鍐荤粨鐨勪繚璇侀噾
    """
    try:
        order = await OrderExecutor.cancel_order(
            db=db,
            order_id=order_id,
            user_id=current_user.id,
        )
        
        await db.commit()
        await db.refresh(order)
        
        return OrderResponse(
            id=order.id,
            user_id=order.user_id,
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            status=order.status,
            leverage=order.leverage,
            position_side=order.position_side,
            reduce_only=order.reduce_only,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            price=order.price,
            trigger_price=order.trigger_price,
            avg_fill_price=order.avg_fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            commission=order.commission,
            realized_pnl=order.realized_pnl,
            created_at=order.created_at.isoformat() + "Z",
            filled_at=order.filled_at.isoformat() + "Z" if order.filled_at else None,
        )
        
    except OrderNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    except OrderError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ==================== 姝㈢泩姝㈡崯鐩堜簭棰勮 ====================

class TpSlPreviewRequest(BaseModel):
    """姝㈢泩姝㈡崯鐩堜簭棰勮璇锋眰"""
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., example="long")  # long or short
    quantity: Decimal = Field(..., gt=0, example=0.01)
    entry_price: Decimal = Field(..., gt=0, example=78000)
    take_profit: Optional[Decimal] = Field(default=None, example=85000)
    stop_loss: Optional[Decimal] = Field(default=None, example=75000)
    leverage: int = Field(default=1, ge=1, le=125, example=20)


class TpSlPreviewResponse(BaseModel):
    """姝㈢泩姝㈡崯鐩堜簭棰勮鍝嶅簲"""
    take_profit_pnl: float  # 姝㈢泩鐩堜簭 (USDT)
    take_profit_pct: float  # 姝㈢泩鏀剁泭鐜?(%)
    stop_loss_pnl: float    # 姝㈡崯鐩堜簭 (USDT)
    stop_loss_pct: float    # 姝㈡崯鏀剁泭鐜?(%)
    risk_reward_ratio: float  # 椋庨櫓鍥炴姤姣?
    margin_required: float  # 鎵€闇€淇濊瘉閲?
    notional: float         # 鍚嶄箟浠峰€?


@router.post("/tp-sl-preview", response_model=TpSlPreviewResponse)
async def preview_tp_sl(request: TpSlPreviewRequest):
    """
    璁＄畻姝㈢泩姝㈡崯鐨勯璁＄泩浜?
    
    鐢ㄤ簬鍦ㄤ笅鍗曞墠棰勮娼滃湪鐨勭泩浜忔儏鍐?
    """
    from app.services.margin.calculator import MarginCalculator
    from app.models.position import PositionSide
    
    side = PositionSide.LONG if request.side.lower() == "long" else PositionSide.SHORT
    
    result = MarginCalculator.calculate_tp_sl_preview(
        side=side,
        quantity=request.quantity,
        entry_price=request.entry_price,
        take_profit=request.take_profit,
        stop_loss=request.stop_loss,
        leverage=request.leverage,
    )
    
    notional = request.quantity * request.entry_price
    margin = notional / Decimal(request.leverage)
    
    return TpSlPreviewResponse(
        take_profit_pnl=float(result["take_profit_pnl"]),
        take_profit_pct=float(result["take_profit_pct"]),
        stop_loss_pnl=float(result["stop_loss_pnl"]),
        stop_loss_pct=float(result["stop_loss_pct"]),
        risk_reward_ratio=float(result["risk_reward_ratio"]),
        margin_required=float(margin.quantize(Decimal("0.01"))),
        notional=float(notional.quantize(Decimal("0.01"))),
    )


# ==================== 鏉犳潌淇℃伅鏌ヨ ====================

class LeverageInfoRequest(BaseModel):
    """鏉犳潌淇℃伅鏌ヨ璇锋眰"""
    symbol: str = Field(..., example="BTCUSDT")
    notional: Optional[Decimal] = Field(default=None, example=10000)
    quantity: Optional[Decimal] = Field(default=None, example=0.1)
    price: Optional[Decimal] = Field(default=None, example=78000)


class LeverageInfoResponse(BaseModel):
    """鏉犳潌淇℃伅鍝嶅簲"""
    symbol: str
    max_leverage: int           # 鏈€澶ф潬鏉?
    maintenance_margin_rate: float  # 缁存寔淇濊瘉閲戠巼 (%)
    notional: float             # 鍚嶄箟浠峰€?
    min_notional: float = 5.0   # 鏈€灏忓悕涔変环鍊?


@router.post("/leverage-info", response_model=LeverageInfoResponse)
async def get_leverage_info(request: LeverageInfoRequest):
    """
    鏌ヨ鎸囧畾浠撲綅鐨勬渶澶ф潬鏉嗗拰缁存寔淇濊瘉閲戠巼
    
    鏍规嵁甯佸畨瑙勫垯锛屼粨浣嶈秺澶э紝鍏佽鐨勬渶澶ф潬鏉嗚秺浣?
    """
    from app.services.margin.leverage_tiers import (
        get_max_leverage,
        get_maintenance_margin_rate,
        MIN_NOTIONAL_VALUE,
    )
    
    # 璁＄畻鍚嶄箟浠峰€?
    if request.notional:
        notional = request.notional
    elif request.quantity and request.price:
        notional = request.quantity * request.price
    else:
        notional = Decimal("0")
    
    max_lev = get_max_leverage(request.symbol, notional)
    mmr = get_maintenance_margin_rate(request.symbol, notional)
    
    return LeverageInfoResponse(
        symbol=request.symbol.upper(),
        max_leverage=max_lev,
        maintenance_margin_rate=float(mmr * 100),  # 杞负鐧惧垎姣?
        notional=float(notional),
        min_notional=float(MIN_NOTIONAL_VALUE),
    )

