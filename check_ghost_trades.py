import asyncio
import os
import sys

# Append backend path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.order import Order
from app.models.strategy import TradeMemory
from app.models.position import Position

async def check_ghost_trades():
    async with AsyncSessionLocal() as db:
        print("\n=== Recent Orders ===")
        res = await db.execute(
            select(Order).order_by(Order.created_at.desc()).limit(10)
        )
        for o in res.scalars():
            print(f"[{o.created_at}] Order {o.id} | {o.symbol} {o.side} {o.order_type} | qty={o.quantity} | note='{o.note}'")

        print("\n=== Recent Trade Memories ===")
        res2 = await db.execute(
            select(TradeMemory).order_by(TradeMemory.created_at.desc()).limit(10)
        )
        for m in res2.scalars():
            print(f"[{m.created_at}] Memory {m.id} | source='{m.source}' | strat_name='{m.strategy_name}' | open_reason='{m.open_reason}'")

        print("\n=== Open Positions ===")
        res3 = await db.execute(
            select(Position).where(Position.status == "OPEN").limit(5)
        )
        for p in res3.scalars():
            print(f"Position {p.id} | {p.symbol} {p.side} | source='{p.source}'")

if __name__ == "__main__":
    asyncio.run(check_ghost_trades())
