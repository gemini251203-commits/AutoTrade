"""
Funding Rate API 鈥?璧勯噾璐圭巼绔偣
=================================
鎻愪緵璧勯噾璐圭巼鏌ヨ鎺ュ彛, 鏀寔鎵€鏈夌郴缁熷唴甯佺

绔偣:
- GET  /api/funding/rates          鎵€鏈変氦鏄撳褰撳墠璐圭巼
- GET  /api/funding/rates/{symbol} 鍗曚釜浜ゆ槗瀵硅鎯?(鍚勾鍖?
- GET  /api/funding/history/{symbol} 鍘嗗彶璐圭巼
- GET  /api/funding/my-fees        鐢ㄦ埛绱琚墸鐨勮祫閲戣垂鐢?
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, DbSession, CurrentUser
from app.services.funding_rate import funding_rate_service, FundingRateService

router = APIRouter()


@router.get("/rates")
async def get_all_rates():
    """
    鑾峰彇鎵€鏈変氦鏄撳鐨勫綋鍓嶈祫閲戣垂鐜?(浠庡唴瀛樼紦瀛樿鍙?

    杩斿洖绯荤粺涓墍鏈夊竵绉嶇殑璐圭巼銆佹爣璁颁环銆佷笅娆＄粨绠楁椂闂?
    """
    cached = FundingRateService.get_all_cached_rates()
    if not cached:
        # 缂撳瓨涓虹┖, 灏濊瘯鍗虫椂閲囬泦
        await funding_rate_service.fetch_all_rates()
        cached = FundingRateService.get_all_cached_rates()

    result = []
    for symbol, data in cached.items():
        rate = float(data.get("lastFundingRate", 0))
        annualized = rate * 3 * 365 * 100
        result.append({
            "symbol": symbol,
            "mark_price": data.get("markPrice", "0"),
            "funding_rate": data.get("lastFundingRate", "0"),
            "funding_rate_pct": f"{rate * 100:.4f}%",
            "annualized_pct": f"{annualized:.2f}%",
            "next_funding_time": data.get("nextFundingTime", 0),
            "direction": "澶氬ご浠樿垂" if rate > 0 else "绌哄ご浠樿垂" if rate < 0 else "闆惰垂鐜?,
            "updated_at": data.get("updated_at"),
        })

    # 鎸夎垂鐜囩粷瀵瑰€奸檷搴忔帓鍒?
    result.sort(key=lambda x: abs(float(x.get("funding_rate", 0))), reverse=True)
    return {"rates": result, "count": len(result)}


@router.get("/rates/{symbol}")
async def get_rate_detail(symbol: str):
    """
    鑾峰彇鍗曚釜浜ゆ槗瀵圭殑瀹屾暣璐圭巼淇℃伅 (鍚勾鍖栥€佷笅娆＄粨绠楀€掕鏃?
    """
    info = await funding_rate_service.get_funding_info(symbol.upper())
    if not info:
        return {"error": f"鏃犳硶鑾峰彇 {symbol} 鐨勮垂鐜囦俊鎭?}
    return info


@router.get("/history/{symbol}")
async def get_rate_history(symbol: str, limit: int = Query(100, ge=1, le=1000)):
    """
    鑾峰彇鍘嗗彶璧勯噾璐圭巼 (鐢ㄤ簬鍥捐〃灞曠ず)

    鐩存帴杞彂甯佸畨 /fapi/v1/fundingRate
    """
    from app.services.exchange import BinanceClient
    client = BinanceClient()
    history = await client.get_funding_history(symbol.upper(), limit)
    return {"symbol": symbol.upper(), "history": history, "count": len(history)}


@router.get("/my-fees")
async def get_my_fees(
    db: DbSession,
    user: CurrentUser,
):
    """
    鏌ヨ褰撳墠鐢ㄦ埛鐨勮祫閲戣垂鐜囩疮璁′俊鎭?

    鍖呭惈:
    - 鍚勪粨浣嶇殑绱璐圭敤
    - 鎬昏璐圭敤
    """
    from app.models.position import Position, PositionStatus
    from app.models.wallet_transaction import WalletTransaction, TransactionType

    # 娲昏穬浠撲綅鐨勮垂鐢?
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user.id,
            Position.status == PositionStatus.OPEN,
        )
    )
    open_positions = pos_result.scalars().all()

    position_fees = []
    for pos in open_positions:
        fee = float(getattr(pos, "total_funding_fee", 0) or 0)
        position_fees.append({
            "position_id": pos.id,
            "symbol": pos.symbol,
            "side": pos.side.value,
            "size": float(pos.size),
            "total_funding_fee": fee,
        })

    # 鎬昏 (浠庢祦姘寸粺璁?
    total_result = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.user_id == user.id,
            WalletTransaction.type == TransactionType.FUNDING.value,
        )
    )
    total_funding = float(total_result.scalar() or 0)

    # 鏈€杩?20 鏉¤祫閲戣垂鐜囨祦姘?
    recent_result = await db.execute(
        select(WalletTransaction).where(
            WalletTransaction.user_id == user.id,
            WalletTransaction.type == TransactionType.FUNDING.value,
        ).order_by(WalletTransaction.created_at.desc()).limit(20)
    )
    recent_txs = [
        {
            "id": tx.id,
            "amount": float(tx.amount),
            "balance_after": float(tx.balance_after),
            "note": tx.note,
            "created_at": tx.created_at.isoformat() + "Z" if tx.created_at else None,
        }
        for tx in recent_result.scalars().all()
    ]

    return {
        "total_funding_fee": total_funding,
        "open_position_fees": position_fees,
        "recent_transactions": recent_txs,
    }
