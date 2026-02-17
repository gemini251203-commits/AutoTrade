"""Backfill trade journal from closed positions"""
import asyncio
from app.db.session import AsyncSessionLocal as async_session_factory
from app.models.position import Position, PositionStatus
from app.models.strategy import TradeMemory
from sqlalchemy import select, func
from decimal import Decimal
from datetime import datetime


async def backfill():
    async with async_session_factory() as db:
        # 1. Check existing trade memories
        r2 = await db.execute(select(func.count(TradeMemory.id)))
        cnt = r2.scalar()
        print(f"Existing trade memories: {cnt}")

        # 2. Get all closed positions
        r = await db.execute(
            select(Position).where(Position.status == PositionStatus.CLOSED)
        )
        closed = r.scalars().all()
        print(f"Closed positions: {len(closed)}")

        for p in closed:
            print(f"  #{p.id} {p.symbol} {p.side.value} entry={p.entry_price} pnl={p.realized_pnl} source={p.source} closed={p.closed_at}")

            # Check if already has a trade memory
            existing = await db.execute(
                select(TradeMemory).where(TradeMemory.position_id == p.id)
            )
            if existing.scalar_one_or_none():
                print(f"    -> Already has trade memory, skipping")
                continue

            # Create trade memory
            margin = float(p.margin) if p.margin else 0
            pnl_float = float(p.realized_pnl) if p.realized_pnl else 0
            pnl_pct = (pnl_float / margin * 100) if margin > 0 else 0

            if pnl_float > 0.01:
                trade_result = "win"
            elif pnl_float < -0.01:
                trade_result = "loss"
            else:
                trade_result = "breakeven"

            duration_minutes = None
            if p.created_at and p.closed_at:
                delta = p.closed_at - p.created_at
                duration_minutes = int(delta.total_seconds() / 60)

            source = getattr(p, "source", "manual") or "manual"

            memory = TradeMemory(
                user_id=p.user_id,
                symbol=p.symbol,
                source=source,
                position_id=p.id,
                side=p.side.value if p.side else None,
                entry_price=float(p.entry_price),
                exit_price=0,  # not stored on position
                leverage=p.leverage,
                margin_used=margin,
                trade_result=trade_result,
                pnl_pct=round(pnl_pct, 2),
                pnl_usdt=round(pnl_float, 4),
                duration_minutes=duration_minutes,
                close_reason=source,
                had_stop_loss=p.stop_loss is not None,
                had_take_profit=p.take_profit is not None,
                open_reason=getattr(p, "open_reason", None),
            )
            db.add(memory)
            print(f"    -> Created trade memory: {trade_result} {pnl_float:+.2f} USDT ({pnl_pct:+.1f}%)")

        await db.commit()
        print("Done! Backfill complete.")


asyncio.run(backfill())
