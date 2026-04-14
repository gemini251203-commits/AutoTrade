"""
账户工具 — get_balance, get_positions, get_open_orders
"""

import json
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.position import Position, PositionStatus
from app.models.wallet import Wallet
from ._registry import register_tool


@register_tool
async def get_balance(db: AsyncSession, user_id: int) -> str:
    """查询账户余额"""
    result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        return json.dumps({"error": "钱包未初始化"}, ensure_ascii=False, default=str)

    # ★ 查询已用保证金总额
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    open_positions = pos_result.scalars().all()
    total_margin_used = sum(float(p.margin) for p in open_positions)
    position_count = len(open_positions)

    return json.dumps({
        "available": float(wallet.balance),
        "frozen": float(wallet.frozen),
        "total_equity": float(wallet.total_equity),
        "total_pnl": float(wallet.total_pnl),
        "margin_used": round(total_margin_used, 2),
        "open_positions": position_count,
        "note": "available 是可用余额，margin_used 是当前所有持仓占用的实际保证金",
    }, ensure_ascii=False, default=str)


@register_tool
async def get_positions(db: AsyncSession, user_id: int) -> str:
    """查询当前持仓"""
    result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    positions = result.scalars().all()

    if not positions:
        return json.dumps({"positions": [], "message": "当前无持仓"}, ensure_ascii=False, default=str)

    # 获取实时价格计算未实现盈亏
    from app.services.exchange import BinanceClient
    client = BinanceClient()

    data = []
    for p in positions:
        unrealized_pnl = 0.0
        try:
            ticker = await client.get_ticker(p.symbol)
            mark_price = float(ticker.get("lastPrice", 0)) if ticker else 0
            if mark_price > 0:
                unrealized_pnl = float(p.calculate_unrealized_pnl(Decimal(str(mark_price))))
        except Exception:
            pass

        data.append({
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side.value,
            "size": float(p.size),
            "entry_price": float(p.entry_price),
            "leverage": p.leverage,
            "margin": float(p.margin),
            "unrealized_pnl": unrealized_pnl,
            "stop_loss": float(p.stop_loss) if p.stop_loss else None,
            "take_profit": float(p.take_profit) if p.take_profit else None,
        })
    
    # ★ 汇总信息 — 帮助 AI 准确了解总资金占用
    total_margin = sum(d["margin"] for d in data)
    total_unrealized_pnl = sum(d["unrealized_pnl"] for d in data)
    
    return json.dumps({
        "positions": data,
        "summary": {
            "total_positions": len(data),
            "total_margin_used": round(total_margin, 2),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "note": "margin 字段是交易所实际保证金（USDT），请直接使用此值，不要自行计算",
        },
    }, ensure_ascii=False, default=str)


@register_tool
async def get_open_orders(db: AsyncSession, user_id: int) -> str:
    """查询挂单"""
    result = await db.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
        )
    )
    orders = result.scalars().all()

    if not orders:
        return json.dumps({"orders": [], "message": "当前无挂单"}, ensure_ascii=False, default=str)

    data = [
        {
            "id": o.id,
            "symbol": o.symbol,
            "side": o.side.value,
            "order_type": o.order_type.value,
            "quantity": float(o.quantity),
            "price": float(o.price) if o.price else None,
            "status": o.status.value,
            "leverage": o.leverage,
        }
        for o in orders
    ]
    return json.dumps({"orders": data}, ensure_ascii=False, default=str)
