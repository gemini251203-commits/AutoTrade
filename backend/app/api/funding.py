"""
Funding Rate API — 资金费率端点
=================================
提供资金费率查询接口, 支持所有系统内币种

端点:
- GET  /api/funding/rates          所有交易对当前费率
- GET  /api/funding/rates/{symbol} 单个交易对详情 (含年化)
- GET  /api/funding/history/{symbol} 历史费率
- GET  /api/funding/my-fees        用户累计被扣的资金费用
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
    获取所有交易对的当前资金费率 (从内存缓存读取)

    返回系统中所有币种的费率、标记价、下次结算时间
    """
    cached = FundingRateService.get_all_cached_rates()
    if not cached:
        # 缓存为空, 尝试即时采集
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
            "direction": "多头付费" if rate > 0 else "空头付费" if rate < 0 else "零费率",
            "updated_at": data.get("updated_at"),
        })

    # 按费率绝对值降序排列
    result.sort(key=lambda x: abs(float(x.get("funding_rate", 0))), reverse=True)
    return {"rates": result, "count": len(result)}


@router.get("/rates/{symbol}")
async def get_rate_detail(symbol: str):
    """
    获取单个交易对的完整费率信息 (含年化、下次结算倒计时)
    """
    info = await funding_rate_service.get_funding_info(symbol.upper())
    if not info:
        return {"error": f"无法获取 {symbol} 的费率信息"}
    return info


@router.get("/history/{symbol}")
async def get_rate_history(symbol: str, limit: int = Query(100, ge=1, le=1000)):
    """
    获取历史资金费率 (用于图表展示)

    直接转发币安 /fapi/v1/fundingRate
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
    查询当前用户的资金费率累计信息

    包含:
    - 各仓位的累计费用
    - 总计费用
    """
    from app.models.position import Position, PositionStatus
    from app.models.wallet_transaction import WalletTransaction, TransactionType

    # 活跃仓位的费用
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

    # 总计 (从流水统计)
    total_result = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.user_id == user.id,
            WalletTransaction.type == TransactionType.FUNDING.value,
        )
    )
    total_funding = float(total_result.scalar() or 0)

    # 最近 20 条资金费率流水
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
