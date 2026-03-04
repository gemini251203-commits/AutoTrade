"""
Trade Journal API
==================
交易记忆查询端点

端点:
    GET    /api/journal/           - 获取交易记忆列表
    GET    /api/journal/stats      - 获取交易统计
    DELETE /api/journal/{id}       - 删除单条交易记忆
"""

from typing import Optional, List
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.models.strategy import TradeMemory

from sqlalchemy import select, desc, func


router = APIRouter(tags=["TradeJournal"])


# ==================== Schemas ====================

class TradeMemoryResponse(BaseModel):
    """交易记忆响应"""
    id: int
    symbol: str
    source: Optional[str] = None
    side: Optional[str] = None
    entry_price: Optional[Decimal] = None
    exit_price: Optional[Decimal] = None
    leverage: Optional[int] = None
    margin_used: Optional[Decimal] = None
    trade_result: str
    pnl_pct: Decimal
    pnl_usdt: Optional[Decimal] = None
    duration_minutes: Optional[int] = None
    close_reason: Optional[str] = None
    had_stop_loss: Optional[bool] = None
    had_take_profit: Optional[bool] = None
    open_reason: Optional[str] = None
    indicators_snapshot: Optional[str] = None
    lesson: Optional[str] = None
    strategy_name: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True, "json_encoders": {Decimal: str}}


class JournalStatsResponse(BaseModel):
    """交易统计响应"""
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl_usdt: float
    avg_pnl_pct: float
    avg_duration_min: Optional[float] = None
    by_source: dict = {}


# ==================== Routes ====================

@router.get("/")
async def list_trade_memories(
    current_user: CurrentUser,
    db: DbSession,
    symbol: Optional[str] = None,
    source: Optional[str] = None,
    result: Optional[str] = None,
    limit: int = Query(default=20, le=200),
    offset: int = Query(default=0, ge=0),
):
    """获取交易记忆列表 (带 total 用于分页)"""
    base_filter = [TradeMemory.user_id == current_user.id]
    if symbol:
        base_filter.append(TradeMemory.symbol == symbol.upper())
    if source:
        base_filter.append(TradeMemory.source == source)
    if result:
        base_filter.append(TradeMemory.trade_result == result)

    # 总数
    count_result = await db.execute(
        select(func.count(TradeMemory.id)).where(*base_filter)
    )
    total = count_result.scalar() or 0

    # 分页数据
    query = (
        select(TradeMemory)
        .where(*base_filter)
        .order_by(desc(TradeMemory.created_at))
        .offset(offset)
        .limit(limit)
    )
    db_result = await db.execute(query)
    memories = db_result.scalars().all()
    
    items = [
        TradeMemoryResponse(
            id=m.id,
            symbol=m.symbol,
            source=m.source,
            side=m.side,
            entry_price=m.entry_price,
            exit_price=m.exit_price,
            leverage=m.leverage,
            margin_used=m.margin_used,
            trade_result=m.trade_result,
            pnl_pct=m.pnl_pct,
            pnl_usdt=m.pnl_usdt,
            duration_minutes=m.duration_minutes,
            close_reason=m.close_reason,
            had_stop_loss=m.had_stop_loss,
            had_take_profit=m.had_take_profit,
            open_reason=m.open_reason,
            indicators_snapshot=m.indicators_snapshot,
            lesson=m.lesson,
            strategy_name=m.strategy_name,
            created_at=m.created_at.isoformat() + "Z" if m.created_at else None,
        )
        for m in memories
    ]

    return {"items": items, "total": total}


@router.get("/stats", response_model=JournalStatsResponse)
async def get_journal_stats(
    current_user: CurrentUser,
    db: DbSession,
    symbol: Optional[str] = None,
):
    """获取交易统计"""
    base_filter = [TradeMemory.user_id == current_user.id]
    if symbol:
        base_filter.append(TradeMemory.symbol == symbol.upper())
    
    # 总体统计
    result = await db.execute(
        select(
            func.count(TradeMemory.id).label("total"),
            func.coalesce(func.sum(TradeMemory.pnl_usdt), 0).label("total_pnl"),
            func.coalesce(func.avg(TradeMemory.pnl_pct), 0).label("avg_pnl"),
            func.avg(TradeMemory.duration_minutes).label("avg_dur"),
        )
        .where(*base_filter)
    )
    row = result.one()
    total = row.total or 0
    
    # 按来源分组
    source_result = await db.execute(
        select(
            TradeMemory.source,
            func.count(TradeMemory.id).label("count"),
            func.coalesce(func.sum(TradeMemory.pnl_usdt), 0).label("pnl"),
        )
        .where(*base_filter)
        .group_by(TradeMemory.source)
    )
    by_source = {}
    for sr in source_result.all():
        by_source[sr.source or "unknown"] = {
            "count": sr.count,
            "pnl_usdt": float(sr.pnl or 0),
        }
    
    # win/loss 统计
    win_result = await db.execute(
        select(func.count(TradeMemory.id))
        .where(*base_filter, TradeMemory.trade_result == "win")
    )
    win_count = win_result.scalar() or 0
    
    loss_result = await db.execute(
        select(func.count(TradeMemory.id))
        .where(*base_filter, TradeMemory.trade_result == "loss")
    )
    loss_count = loss_result.scalar() or 0

    return JournalStatsResponse(
        total_trades=total,
        win_count=win_count,
        loss_count=loss_count,
        win_rate=round(win_count / total * 100, 1) if total > 0 else 0,
        total_pnl_usdt=float(row.total_pnl or 0),
        avg_pnl_pct=round(float(row.avg_pnl or 0), 2),
        avg_duration_min=round(float(row.avg_dur), 1) if row.avg_dur else None,
        by_source=by_source,
    )


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """删除单条交易记忆"""
    from fastapi import HTTPException
    
    result = await db.execute(
        select(TradeMemory).where(
            TradeMemory.id == memory_id,
            TradeMemory.user_id == current_user.id,
        )
    )
    memory = result.scalar_one_or_none()
    
    if not memory:
        raise HTTPException(status_code=404, detail="记录不存在")
    
    await db.delete(memory)
    await db.commit()
    
    return {"ok": True}

