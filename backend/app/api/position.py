"""
Position API
=============
仓位管理端点

端点:
    GET  /api/position/           - 获取用户所有仓位
    GET  /api/position/{id}       - 获取单个仓位详情
    POST /api/position/open       - 开仓
    POST /api/position/{id}/close - 平仓
    POST /api/position/{id}/tp-sl - 设置止盈止损
"""

from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.position import Position, PositionSide, PositionStatus, MarginMode
from app.services.trading import PositionManager, InsufficientMarginError, PositionNotFoundError, PositionConflictError


router = APIRouter(tags=["Position"])


# ==================== Schemas ====================

class OpenPositionRequest(BaseModel):
    """开仓请求"""
    symbol: str = Field(..., example="BTCUSDT")
    side: PositionSide = Field(..., example="long")
    quantity: Decimal = Field(..., gt=0, example=0.01)
    entry_price: Decimal = Field(..., gt=0, example=80000)
    leverage: int = Field(default=10, ge=1, le=125, example=10)
    margin_mode: MarginMode = Field(default=MarginMode.CROSS)
    reduce_only: bool = Field(default=False, description="只减仓 (平仓模式)")
    stop_loss: Optional[Decimal] = Field(default=None, example=75000)
    take_profit: Optional[Decimal] = Field(default=None, example=90000)


class ClosePositionRequest(BaseModel):
    """平仓请求"""
    close_price: Decimal = Field(..., gt=0, example=82000)
    quantity: Optional[Decimal] = Field(default=None, gt=0, description="平仓数量，不填则全平")


class SetTpSlRequest(BaseModel):
    """设置止盈止损"""
    stop_loss: Optional[Decimal] = Field(default=None)
    take_profit: Optional[Decimal] = Field(default=None)
    mark_price: Optional[Decimal] = Field(default=None, description="当前标记价格 (用于校验)")


class PositionResponse(BaseModel):
    """仓位响应"""
    model_config = {"from_attributes": True, "json_encoders": {Decimal: str}}

    id: int
    user_id: int
    symbol: str
    side: PositionSide
    status: PositionStatus
    size: Decimal
    entry_price: Decimal
    leverage: int
    margin: Decimal
    margin_mode: MarginMode
    liquidation_price: Optional[Decimal]
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    realized_pnl: Decimal
    created_at: str


class PositionWithPnlResponse(PositionResponse):
    """带未实现盈亏的仓位响应"""
    unrealized_pnl: Optional[Decimal] = None
    roe_percent: Optional[Decimal] = None


class ClosePositionResponse(BaseModel):
    """平仓响应"""
    position: PositionResponse
    realized_pnl: Decimal


# ==================== Routes ====================

@router.get("/", response_model=List[PositionResponse])
async def list_positions(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Optional[PositionStatus] = None,
):
    """
    获取用户所有仓位
    
    可选按状态过滤: open, closed, liquidated
    """
    positions = await PositionManager.get_user_positions(
        db, current_user.id, status_filter
    )
    
    return [
        PositionResponse(
            id=p.id,
            user_id=p.user_id,
            symbol=p.symbol,
            side=p.side,
            status=p.status,
            size=p.size,
            entry_price=p.entry_price,
            leverage=p.leverage,
            margin=p.margin,
            margin_mode=p.margin_mode,
            liquidation_price=p.liquidation_price,
            stop_loss=p.stop_loss,
            take_profit=p.take_profit,
            realized_pnl=p.realized_pnl,
            created_at=p.created_at.isoformat() + "Z",
        )
        for p in positions
    ]


@router.post("/open", response_model=PositionResponse)
async def open_position(
    request: OpenPositionRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    开仓 / 只减仓
    
    ⚠️ 资金原子性: 冻结保证金和创建仓位在同一事务中完成
    
    当 reduce_only=True 时，只能平掉现有仓位，不能开新仓位
    """
    try:
        if request.reduce_only:
            # 只减仓模式 - 执行平仓
            # 确定要平仓的仓位方向 (反向)
            close_side = PositionSide.SHORT if request.side == PositionSide.LONG else PositionSide.LONG
            
            # 查找现有仓位
            existing = await PositionManager.get_open_position(
                db, current_user.id, request.symbol, close_side
            )
            
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"只减仓模式: 没有可平仓的 {close_side.value} 仓位",
                )
            
            # 平仓
            position, pnl = await PositionManager.close_position(
                db=db,
                position_id=existing.id,
                close_price=request.entry_price,
                close_quantity=request.quantity,
            )
            
            await db.commit()
            await db.refresh(position)
            
            return PositionResponse(
                id=position.id,
                user_id=position.user_id,
                symbol=position.symbol,
                side=position.side,
                status=position.status,
                size=position.size,
                entry_price=position.entry_price,
                leverage=position.leverage,
                margin=position.margin,
                margin_mode=position.margin_mode,
                liquidation_price=position.liquidation_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                realized_pnl=position.realized_pnl,
                created_at=position.created_at.isoformat() + "Z",
            )
        else:
            # 正常开仓模式
            
            # ========== 止盈止损价格合理性校验 (与 set_tp_sl 保持一致) ==========
            if request.stop_loss is not None or request.take_profit is not None:
                ref_price = request.entry_price
                is_long = request.side == PositionSide.LONG
                new_sl = request.stop_loss
                new_tp = request.take_profit
                
                if new_sl is not None and new_sl > 0:
                    if is_long and new_sl >= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"多单止损价 ({new_sl}) 必须低于开仓价 ({ref_price})，"
                                   f"否则会立即触发",
                        )
                    if not is_long and new_sl <= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"空单止损价 ({new_sl}) 必须高于开仓价 ({ref_price})，"
                                   f"否则会立即触发",
                        )
                
                if new_tp is not None and new_tp > 0:
                    if is_long and new_tp <= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"多单止盈价 ({new_tp}) 必须高于开仓价 ({ref_price})，"
                                   f"否则会立即触发",
                        )
                    if not is_long and new_tp >= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"空单止盈价 ({new_tp}) 必须低于开仓价 ({ref_price})，"
                                   f"否则会立即触发",
                        )
                
                # 止盈止损不能交叉
                if new_sl and new_tp and new_sl > 0 and new_tp > 0:
                    if is_long and new_sl >= new_tp:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"多单止损 ({new_sl}) 不能高于止盈 ({new_tp})",
                        )
                    if not is_long and new_sl <= new_tp:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"空单止损 ({new_sl}) 不能低于止盈 ({new_tp})",
                        )
            
            position = await PositionManager.open_position(
                db=db,
                user_id=current_user.id,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                entry_price=request.entry_price,
                leverage=request.leverage,
                margin_mode=request.margin_mode,
                stop_loss=request.stop_loss,
                take_profit=request.take_profit,
            )
            
            await db.commit()
            await db.refresh(position)
            
            return PositionResponse(
                id=position.id,
                user_id=position.user_id,
                symbol=position.symbol,
                side=position.side,
                status=position.status,
                size=position.size,
                entry_price=position.entry_price,
                leverage=position.leverage,
                margin=position.margin,
                margin_mode=position.margin_mode,
                liquidation_price=position.liquidation_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                realized_pnl=position.realized_pnl,
                created_at=position.created_at.isoformat() + "Z",
            )
        
    except InsufficientMarginError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except PositionConflictError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"[Position API] Open position failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to open position: {str(e)}",
        )


@router.post("/{position_id}/close", response_model=ClosePositionResponse)
async def close_position(
    position_id: int,
    request: ClosePositionRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    平仓
    
    ⚠️ 资金原子性: 释放保证金和结算盈亏在同一事务中完成
    """
    try:
        # 验证仓位属于当前用户
        from sqlalchemy import select
        result = await db.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        
        if not position:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found",
            )
        
        if position.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Position does not belong to you",
            )
        
        position, pnl = await PositionManager.close_position(
            db=db,
            position_id=position_id,
            close_price=request.close_price,
            close_quantity=request.quantity,
        )
        
        # 提交事务
        await db.commit()
        await db.refresh(position)
        
        return ClosePositionResponse(
            position=PositionResponse(
                id=position.id,
                user_id=position.user_id,
                symbol=position.symbol,
                side=position.side,
                status=position.status,
                size=position.size,
                entry_price=position.entry_price,
                leverage=position.leverage,
                margin=position.margin,
                margin_mode=position.margin_mode,
                liquidation_price=position.liquidation_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                realized_pnl=position.realized_pnl,
                created_at=position.created_at.isoformat() + "Z",
            ),
            realized_pnl=pnl,
        )
        
    except PositionNotFoundError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found",
        )
    except HTTPException:
        # 重新抛出 HTTP 异常
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[Position API] Close position failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to close position: {str(e)}",
        )


@router.post("/{position_id}/tp-sl", response_model=PositionResponse)
async def set_tp_sl(
    position_id: int,
    request: SetTpSlRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """设置止盈止损"""
    from sqlalchemy import select
    
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.user_id == current_user.id,
        )
    )
    position = result.scalar_one_or_none()
    
    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found",
        )
    
    if position.status != PositionStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify closed position",
        )
    
    # ========== 止盈止损价格合理性校验 ==========
    # 使用前端传来的标记价格，若没有则用开仓价
    ref_price = request.mark_price or position.entry_price
    is_long = position.side == PositionSide.LONG
    
    new_sl = request.stop_loss
    new_tp = request.take_profit
    
    if new_sl is not None and new_sl > 0:
        if is_long and new_sl >= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"多单止损价 ({new_sl}) 必须低于当前标记价 ({ref_price})，"
                       f"否则会立即触发或变成止盈",
            )
        if not is_long and new_sl <= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"空单止损价 ({new_sl}) 必须高于当前标记价 ({ref_price})，"
                       f"否则会立即触发或变成止盈",
            )
    
    if new_tp is not None and new_tp > 0:
        if is_long and new_tp <= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"多单止盈价 ({new_tp}) 必须高于当前标记价 ({ref_price})，"
                       f"否则会立即触发或变成止损",
            )
        if not is_long and new_tp >= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"空单止盈价 ({new_tp}) 必须低于当前标记价 ({ref_price})，"
                       f"否则会立即触发或变成止损",
            )
    
    # 止盈止损不能交叉
    final_sl = new_sl if new_sl is not None else position.stop_loss
    final_tp = new_tp if new_tp is not None else position.take_profit
    if final_sl and final_tp and final_sl > 0 and final_tp > 0:
        if is_long and final_sl >= final_tp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"多单止损 ({final_sl}) 不能高于止盈 ({final_tp})",
            )
        if not is_long and final_sl <= final_tp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"空单止损 ({final_sl}) 不能低于止盈 ({final_tp})",
            )
    
    if request.stop_loss is not None:
        position.stop_loss = request.stop_loss
    if request.take_profit is not None:
        position.take_profit = request.take_profit
    
    await db.commit()
    await db.refresh(position)
    
    return PositionResponse(
        id=position.id,
        user_id=position.user_id,
        symbol=position.symbol,
        side=position.side,
        status=position.status,
        size=position.size,
        entry_price=position.entry_price,
        leverage=position.leverage,
        margin=position.margin,
        margin_mode=position.margin_mode,
        liquidation_price=position.liquidation_price,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        realized_pnl=position.realized_pnl,
        created_at=position.created_at.isoformat() + "Z",
    )


# ==================== 动态强平价格 (Cross Margin) ====================

class LiquidationInfoRequest(BaseModel):
    """动态强平价格计算请求"""
    position_id: int
    current_price: Decimal = Field(..., gt=0, description="当前市场价格")


class LiquidationInfoResponse(BaseModel):
    """动态强平价格响应"""
    position_id: int
    symbol: str
    side: str
    margin_mode: str
    entry_price: Decimal
    liquidation_price: Decimal
    is_dynamic: bool
    unrealized_pnl: Decimal
    margin_ratio: Decimal  # 保证金率 (>= 1.0 时触发强平)
    account_equity: Decimal  # 账户权益 (仅全仓模式有意义)


@router.post("/liquidation-info", response_model=LiquidationInfoResponse)
async def get_liquidation_info(
    request: LiquidationInfoRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取仓位动态强平信息
    
    - 逐仓模式: 返回固定强平价 (开仓时确定)
    - 全仓模式: 根据账户权益动态计算强平价
    
    ⚠️ 全仓模式下强平价会随账户余额和其他仓位盈亏变化
    """
    from sqlalchemy import select, and_
    from app.services.margin import MarginCalculator
    from app.services.wallet import WalletManager
    
    # 1. 获取指定仓位
    result = await db.execute(
        select(Position).where(
            Position.id == request.position_id,
            Position.user_id == current_user.id,
            Position.status == PositionStatus.OPEN,
        )
    )
    position = result.scalar_one_or_none()
    
    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found or not open",
        )
    
    # 2. 计算该仓位的未实现盈亏 (使用 Position 模型方法)
    unrealized_pnl = position.calculate_unrealized_pnl(request.current_price)
    
    # 3. 根据保证金模式计算强平价格
    if position.margin_mode == MarginMode.ISOLATED:
        # 逐仓: 使用固定强平价
        liq_price = position.liquidation_price or MarginCalculator.calculate_isolated_liquidation_price(
            entry_price=position.entry_price,
            leverage=position.leverage,
            side=position.side,
        )
        is_dynamic = False
        account_equity = position.margin + unrealized_pnl
    else:
        # 全仓: 动态计算
        # 3.1 获取账户余额 (可用 + 冻结)
        wallet = await WalletManager.get_wallet(db, current_user.id)
        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found",
            )
        
        account_balance = wallet.balance + wallet.frozen
        
        # 3.2 获取所有其他仓位的保证金和盈亏
        other_positions = await db.execute(
            select(Position).where(
                and_(
                    Position.user_id == current_user.id,
                    Position.id != position.id,
                    Position.status == PositionStatus.OPEN,
                )
            )
        )
        other_pos_list = list(other_positions.scalars().all())
        
        other_positions_margin = sum(p.margin for p in other_pos_list)
        total_unrealized_pnl = unrealized_pnl + sum(
            p.calculate_unrealized_pnl(request.current_price)
            for p in other_pos_list
        )
        
        # 3.3 计算动态强平价
        liq_price = MarginCalculator.calculate_cross_liquidation_price(
            entry_price=position.entry_price,
            quantity=position.size,
            position_margin=position.margin,
            account_balance=account_balance,
            unrealized_pnl=total_unrealized_pnl,
            other_positions_margin=other_positions_margin,
            side=position.side,
        )
        is_dynamic = True
        account_equity = account_balance + total_unrealized_pnl
    
    # 4. 计算保证金率
    maintenance_margin = position.size * position.entry_price * Decimal("0.004")
    equity_for_position = position.margin + unrealized_pnl
    
    if equity_for_position > 0:
        margin_ratio = maintenance_margin / equity_for_position
    else:
        margin_ratio = Decimal("999")  # 已爆仓
    
    return LiquidationInfoResponse(
        position_id=position.id,
        symbol=position.symbol,
        side=position.side.value,
        margin_mode=position.margin_mode.value,
        entry_price=position.entry_price,
        liquidation_price=liq_price,
        is_dynamic=is_dynamic,
        unrealized_pnl=unrealized_pnl.quantize(Decimal("0.01")),
        margin_ratio=margin_ratio.quantize(Decimal("0.0001")),
        account_equity=account_equity.quantize(Decimal("0.01")),
    )

