"""
Order API (合约交易版)
=======================
订单管理端点

端点:
    GET  /api/order/              - 获取用户订单列表
    POST /api/order/              - 创建订单
    POST /api/order/{id}/cancel   - 取消订单
    GET  /api/order/{id}          - 获取订单详情
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
    """创建订单请求"""
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
    """订单响应"""
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

    @classmethod
    def from_order(cls, o) -> "OrderResponse":
        return cls(
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
    获取用户订单列表
    
    可选过滤条件:
    - status_filter: pending, open, filled, cancelled
    - symbol: BTCUSDT 等
    """
    orders = await OrderExecutor.get_user_orders(
        db, current_user.id, status_filter, symbol, limit
    )
    
    return [
        OrderResponse.from_order(o)
        for o in orders
    ]


@router.post("/", response_model=OrderResponse)
async def create_order(
    request: OrderCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    创建订单 (直接通过 OrderExecutor)
    
    订单类型:
    - market: 市价单 (立即成交)
    - limit: 限价单 (挂单等待)
    - stop_market: 止损市价单 (需要 trigger_price)
    - stop_limit: 止损限价单 (需要 trigger_price + price)
    - take_profit_market: 止盈市价单
    - take_profit_limit: 止盈限价单
    """
    try:
        # 基础风控: 最大杠杆限制
        from app.core.risk_config import risk_config
        rc = risk_config.load_for_user(current_user.id)
        max_lev = rc.get("max_leverage", 20)
        if request.leverage > max_lev:
            raise OrderError(f"杠杆 {request.leverage}x 超过风控上限 {max_lev}x")
        
        order = await OrderExecutor.create_order(
            db=db,
            user_id=current_user.id,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            trigger_price=request.trigger_price,
            leverage=request.leverage,
            position_side=request.position_side,
            reduce_only=request.reduce_only,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            note=request.note or "",
        )
        
        await db.commit()
        await db.refresh(order)
        
        return OrderResponse.from_order(order)
        
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
    取消订单
    
    只有活跃订单 (pending/open/partial) 可以取消
    取消后会释放冻结的保证金
    """
    try:
        order = await OrderExecutor.cancel_order(
            db=db,
            order_id=order_id,
            user_id=current_user.id,
        )
        
        await db.commit()
        await db.refresh(order)
        
        return OrderResponse.from_order(order)
        
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


# ==================== 止盈止损盈亏预览 ====================

class TpSlPreviewRequest(BaseModel):
    """止盈止损盈亏预览请求"""
    symbol: str = Field(..., example="BTCUSDT")
    side: str = Field(..., example="long")  # long or short
    quantity: Decimal = Field(..., gt=0, example=0.01)
    entry_price: Decimal = Field(..., gt=0, example=78000)
    take_profit: Optional[Decimal] = Field(default=None, example=85000)
    stop_loss: Optional[Decimal] = Field(default=None, example=75000)
    leverage: int = Field(default=1, ge=1, le=125, example=20)


class TpSlPreviewResponse(BaseModel):
    """止盈止损盈亏预览响应"""
    model_config = {"json_encoders": {Decimal: str}}

    take_profit_pnl: Decimal  # 止盈盈亏 (USDT)
    take_profit_pct: Decimal  # 止盈收益率 (%)
    stop_loss_pnl: Decimal    # 止损盈亏 (USDT)
    stop_loss_pct: Decimal    # 止损收益率 (%)
    risk_reward_ratio: Decimal  # 风险回报比
    margin_required: Decimal  # 所需保证金
    notional: Decimal         # 名义价值


@router.post("/tp-sl-preview", response_model=TpSlPreviewResponse)
async def preview_tp_sl(request: TpSlPreviewRequest):
    """
    计算止盈止损的预计盈亏
    
    用于在下单前预览潜在的盈亏情况
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


# ==================== 杠杆信息查询 ====================

class LeverageInfoRequest(BaseModel):
    """杠杆信息查询请求"""
    symbol: str = Field(..., example="BTCUSDT")
    notional: Optional[Decimal] = Field(default=None, example=10000)
    quantity: Optional[Decimal] = Field(default=None, example=0.1)
    price: Optional[Decimal] = Field(default=None, example=78000)


class LeverageInfoResponse(BaseModel):
    """杠杆信息响应"""
    symbol: str
    max_leverage: int           # 最大杠杆
    maintenance_margin_rate: float  # 维持保证金率 (%)
    notional: float             # 名义价值
    min_notional: float = 5.0   # 最小名义价值


@router.post("/leverage-info", response_model=LeverageInfoResponse)
async def get_leverage_info(request: LeverageInfoRequest):
    """
    查询指定仓位的最大杠杆和维持保证金率
    
    根据币安规则，仓位越大，允许的最大杠杆越低
    """
    from app.services.margin.leverage_tiers import (
        get_max_leverage,
        get_maintenance_margin_rate,
        MIN_NOTIONAL_VALUE,
    )
    
    # 计算名义价值
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
        maintenance_margin_rate=float(mmr * 100),  # 转为百分比
        notional=float(notional),
        min_notional=float(MIN_NOTIONAL_VALUE),
    )

