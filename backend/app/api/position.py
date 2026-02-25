"""
Position API
=============
浠撲綅绠＄悊绔偣

绔偣:
    GET  /api/position/           - 鑾峰彇鐢ㄦ埛鎵€鏈変粨浣?
    GET  /api/position/{id}       - 鑾峰彇鍗曚釜浠撲綅璇︽儏
    POST /api/position/open       - 寮€浠?
    POST /api/position/{id}/close - 骞充粨
    POST /api/position/{id}/tp-sl - 璁剧疆姝㈢泩姝㈡崯
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
    """寮€浠撹姹?""
    symbol: str = Field(..., example="BTCUSDT")
    side: PositionSide = Field(..., example="long")
    quantity: Decimal = Field(..., gt=0, example=0.01)
    entry_price: Decimal = Field(..., gt=0, example=80000)
    leverage: int = Field(default=10, ge=1, le=125, example=10)
    margin_mode: MarginMode = Field(default=MarginMode.CROSS)
    reduce_only: bool = Field(default=False, description="鍙噺浠?(骞充粨妯″紡)")
    stop_loss: Optional[Decimal] = Field(default=None, example=75000)
    take_profit: Optional[Decimal] = Field(default=None, example=90000)


class ClosePositionRequest(BaseModel):
    """骞充粨璇锋眰"""
    close_price: Decimal = Field(..., gt=0, example=82000)
    quantity: Optional[Decimal] = Field(default=None, gt=0, description="骞充粨鏁伴噺锛屼笉濉垯鍏ㄥ钩")


class SetTpSlRequest(BaseModel):
    """璁剧疆姝㈢泩姝㈡崯"""
    stop_loss: Optional[Decimal] = Field(default=None)
    take_profit: Optional[Decimal] = Field(default=None)
    mark_price: Optional[Decimal] = Field(default=None, description="褰撳墠鏍囪浠锋牸 (鐢ㄤ簬鏍￠獙)")


class PositionResponse(BaseModel):
    """浠撲綅鍝嶅簲"""
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
    """甯︽湭瀹炵幇鐩堜簭鐨勪粨浣嶅搷搴?""
    unrealized_pnl: Optional[Decimal] = None
    roe_percent: Optional[Decimal] = None


class ClosePositionResponse(BaseModel):
    """骞充粨鍝嶅簲"""
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
    鑾峰彇鐢ㄦ埛鎵€鏈変粨浣?
    
    鍙€夋寜鐘舵€佽繃婊? open, closed, liquidated
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
    寮€浠?/ 鍙噺浠?
    
    鈿狅笍 璧勯噾鍘熷瓙鎬? 鍐荤粨淇濊瘉閲戝拰鍒涘缓浠撲綅鍦ㄥ悓涓€浜嬪姟涓畬鎴?
    
    褰?reduce_only=True 鏃讹紝鍙兘骞虫帀鐜版湁浠撲綅锛屼笉鑳藉紑鏂颁粨浣?
    """
    try:
        if request.reduce_only:
            # 鍙噺浠撴ā寮?- 鎵ц骞充粨
            # 纭畾瑕佸钩浠撶殑浠撲綅鏂瑰悜 (鍙嶅悜)
            close_side = PositionSide.SHORT if request.side == PositionSide.LONG else PositionSide.LONG
            
            # 鏌ユ壘鐜版湁浠撲綅
            existing = await PositionManager.get_open_position(
                db, current_user.id, request.symbol, close_side
            )
            
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"鍙噺浠撴ā寮? 娌℃湁鍙钩浠撶殑 {close_side.value} 浠撲綅",
                )
            
            # 骞充粨
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
            # 姝ｅ父寮€浠撴ā寮?
            
            # ========== 姝㈢泩姝㈡崯浠锋牸鍚堢悊鎬ф牎楠?(涓?set_tp_sl 淇濇寔涓€鑷? ==========
            if request.stop_loss is not None or request.take_profit is not None:
                ref_price = request.entry_price
                is_long = request.side == PositionSide.LONG
                new_sl = request.stop_loss
                new_tp = request.take_profit
                
                if new_sl is not None and new_sl > 0:
                    if is_long and new_sl >= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"澶氬崟姝㈡崯浠?({new_sl}) 蹇呴』浣庝簬寮€浠撲环 ({ref_price})锛?
                                   f"鍚﹀垯浼氱珛鍗宠Е鍙?,
                        )
                    if not is_long and new_sl <= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"绌哄崟姝㈡崯浠?({new_sl}) 蹇呴』楂樹簬寮€浠撲环 ({ref_price})锛?
                                   f"鍚﹀垯浼氱珛鍗宠Е鍙?,
                        )
                
                if new_tp is not None and new_tp > 0:
                    if is_long and new_tp <= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"澶氬崟姝㈢泩浠?({new_tp}) 蹇呴』楂樹簬寮€浠撲环 ({ref_price})锛?
                                   f"鍚﹀垯浼氱珛鍗宠Е鍙?,
                        )
                    if not is_long and new_tp >= ref_price:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"绌哄崟姝㈢泩浠?({new_tp}) 蹇呴』浣庝簬寮€浠撲环 ({ref_price})锛?
                                   f"鍚﹀垯浼氱珛鍗宠Е鍙?,
                        )
                
                # 姝㈢泩姝㈡崯涓嶈兘浜ゅ弶
                if new_sl and new_tp and new_sl > 0 and new_tp > 0:
                    if is_long and new_sl >= new_tp:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"澶氬崟姝㈡崯 ({new_sl}) 涓嶈兘楂樹簬姝㈢泩 ({new_tp})",
                        )
                    if not is_long and new_sl <= new_tp:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"绌哄崟姝㈡崯 ({new_sl}) 涓嶈兘浣庝簬姝㈢泩 ({new_tp})",
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
    骞充粨
    
    鈿狅笍 璧勯噾鍘熷瓙鎬? 閲婃斁淇濊瘉閲戝拰缁撶畻鐩堜簭鍦ㄥ悓涓€浜嬪姟涓畬鎴?
    """
    try:
        # 楠岃瘉浠撲綅灞炰簬褰撳墠鐢ㄦ埛
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
        
        # 鎻愪氦浜嬪姟
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
        # 閲嶆柊鎶涘嚭 HTTP 寮傚父
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
    """璁剧疆姝㈢泩姝㈡崯"""
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
    
    # ========== 姝㈢泩姝㈡崯浠锋牸鍚堢悊鎬ф牎楠?==========
    # 浣跨敤鍓嶇浼犳潵鐨勬爣璁颁环鏍硷紝鑻ユ病鏈夊垯鐢ㄥ紑浠撲环
    ref_price = request.mark_price or position.entry_price
    is_long = position.side == PositionSide.LONG
    
    new_sl = request.stop_loss
    new_tp = request.take_profit
    
    if new_sl is not None and new_sl > 0:
        if is_long and new_sl >= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"澶氬崟姝㈡崯浠?({new_sl}) 蹇呴』浣庝簬褰撳墠鏍囪浠?({ref_price})锛?
                       f"鍚﹀垯浼氱珛鍗宠Е鍙戞垨鍙樻垚姝㈢泩",
            )
        if not is_long and new_sl <= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"绌哄崟姝㈡崯浠?({new_sl}) 蹇呴』楂樹簬褰撳墠鏍囪浠?({ref_price})锛?
                       f"鍚﹀垯浼氱珛鍗宠Е鍙戞垨鍙樻垚姝㈢泩",
            )
    
    if new_tp is not None and new_tp > 0:
        if is_long and new_tp <= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"澶氬崟姝㈢泩浠?({new_tp}) 蹇呴』楂樹簬褰撳墠鏍囪浠?({ref_price})锛?
                       f"鍚﹀垯浼氱珛鍗宠Е鍙戞垨鍙樻垚姝㈡崯",
            )
        if not is_long and new_tp >= ref_price:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"绌哄崟姝㈢泩浠?({new_tp}) 蹇呴』浣庝簬褰撳墠鏍囪浠?({ref_price})锛?
                       f"鍚﹀垯浼氱珛鍗宠Е鍙戞垨鍙樻垚姝㈡崯",
            )
    
    # 姝㈢泩姝㈡崯涓嶈兘浜ゅ弶
    final_sl = new_sl if new_sl is not None else position.stop_loss
    final_tp = new_tp if new_tp is not None else position.take_profit
    if final_sl and final_tp and final_sl > 0 and final_tp > 0:
        if is_long and final_sl >= final_tp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"澶氬崟姝㈡崯 ({final_sl}) 涓嶈兘楂樹簬姝㈢泩 ({final_tp})",
            )
        if not is_long and final_sl <= final_tp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"绌哄崟姝㈡崯 ({final_sl}) 涓嶈兘浣庝簬姝㈢泩 ({final_tp})",
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


# ==================== 鍔ㄦ€佸己骞充环鏍?(Cross Margin) ====================

class LiquidationInfoRequest(BaseModel):
    """鍔ㄦ€佸己骞充环鏍艰绠楄姹?""
    position_id: int
    current_price: Decimal = Field(..., gt=0, description="褰撳墠甯傚満浠锋牸")


class LiquidationInfoResponse(BaseModel):
    """鍔ㄦ€佸己骞充环鏍煎搷搴?""
    position_id: int
    symbol: str
    side: str
    margin_mode: str
    entry_price: Decimal
    liquidation_price: Decimal
    is_dynamic: bool
    unrealized_pnl: Decimal
    margin_ratio: Decimal  # 淇濊瘉閲戠巼 (>= 1.0 鏃惰Е鍙戝己骞?
    account_equity: Decimal  # 璐︽埛鏉冪泭 (浠呭叏浠撴ā寮忔湁鎰忎箟)


@router.post("/liquidation-info", response_model=LiquidationInfoResponse)
async def get_liquidation_info(
    request: LiquidationInfoRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    鑾峰彇浠撲綅鍔ㄦ€佸己骞充俊鎭?
    
    - 閫愪粨妯″紡: 杩斿洖鍥哄畾寮哄钩浠?(寮€浠撴椂纭畾)
    - 鍏ㄤ粨妯″紡: 鏍规嵁璐︽埛鏉冪泭鍔ㄦ€佽绠楀己骞充环
    
    鈿狅笍 鍏ㄤ粨妯″紡涓嬪己骞充环浼氶殢璐︽埛浣欓鍜屽叾浠栦粨浣嶇泩浜忓彉鍖?
    """
    from sqlalchemy import select, and_
    from app.services.margin import MarginCalculator
    from app.services.wallet import WalletManager
    
    # 1. 鑾峰彇鎸囧畾浠撲綅
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
    
    # 2. 璁＄畻璇ヤ粨浣嶇殑鏈疄鐜扮泩浜?(浣跨敤 Position 妯″瀷鏂规硶)
    unrealized_pnl = position.calculate_unrealized_pnl(request.current_price)
    
    # 3. 鏍规嵁淇濊瘉閲戞ā寮忚绠楀己骞充环鏍?
    if position.margin_mode == MarginMode.ISOLATED:
        # 閫愪粨: 浣跨敤鍥哄畾寮哄钩浠?
        liq_price = position.liquidation_price or MarginCalculator.calculate_isolated_liquidation_price(
            entry_price=position.entry_price,
            leverage=position.leverage,
            side=position.side,
        )
        is_dynamic = False
        account_equity = position.margin + unrealized_pnl
    else:
        # 鍏ㄤ粨: 鍔ㄦ€佽绠?
        # 3.1 鑾峰彇璐︽埛浣欓 (鍙敤 + 鍐荤粨)
        wallet = await WalletManager.get_wallet(db, current_user.id)
        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found",
            )
        
        account_balance = wallet.balance + wallet.frozen
        
        # 3.2 鑾峰彇鎵€鏈夊叾浠栦粨浣嶇殑淇濊瘉閲戝拰鐩堜簭
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
        
        # 3.3 璁＄畻鍔ㄦ€佸己骞充环
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
    
    # 4. 璁＄畻淇濊瘉閲戠巼
    maintenance_margin = position.size * position.entry_price * Decimal("0.004")
    equity_for_position = position.margin + unrealized_pnl
    
    if equity_for_position > 0:
        margin_ratio = maintenance_margin / equity_for_position
    else:
        margin_ratio = Decimal("999")  # 宸茬垎浠?
    
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

