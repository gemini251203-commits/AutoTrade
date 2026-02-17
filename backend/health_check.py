"""Health check: query trading stats from DB"""
import asyncio
from app.db.session import AsyncSessionLocal
from app.models.position import Position, PositionStatus
from app.models.order import Order
from app.models.strategy import TradeMemory
from app.models.wallet import Wallet
from sqlalchemy import select, func, case
from decimal import Decimal


async def health_check():
    async with AsyncSessionLocal() as db:
        # 1. Wallet status
        r = await db.execute(select(Wallet))
        wallets = r.scalars().all()
        for w in wallets:
            print(f"=== WALLET (user {w.user_id}) ===")
            print(f"  Balance: {w.balance} USDT")
            print(f"  Frozen: {w.frozen} USDT")
            print(f"  Total Equity: {w.total_equity} USDT")
            print(f"  Total PnL: {w.total_pnl} USDT")

        # 2. Open positions
        r = await db.execute(select(Position).where(Position.status == PositionStatus.OPEN))
        opens = r.scalars().all()
        print(f"\n=== OPEN POSITIONS: {len(opens)} ===")
        for p in opens:
            print(f"  #{p.id} {p.symbol} {p.side.value} qty={p.size} entry={p.entry_price} margin={p.margin} lev={p.leverage}x sl={p.stop_loss} tp={p.take_profit} src={p.source}")

        # 3. Closed positions
        r = await db.execute(select(Position).where(Position.status == PositionStatus.CLOSED))
        closed = r.scalars().all()
        print(f"\n=== CLOSED POSITIONS: {len(closed)} ===")
        total_pnl = Decimal("0")
        wins = 0
        losses = 0
        for p in closed:
            pnl = p.realized_pnl or Decimal("0")
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            print(f"  #{p.id} {p.symbol} {p.side.value} entry={p.entry_price} pnl={pnl:+.4f} src={p.source} opened={p.created_at} closed={p.closed_at}")
        
        if closed:
            print(f"\n  --- Summary ---")
            print(f"  Total trades: {len(closed)}")
            print(f"  Wins: {wins}, Losses: {losses}")
            print(f"  Win rate: {wins/len(closed)*100:.1f}%")
            print(f"  Total PnL: {total_pnl:+.4f} USDT")

        # 4. Trade memories (journal)
        r = await db.execute(select(func.count(TradeMemory.id)))
        mem_count = r.scalar()
        print(f"\n=== TRADE JOURNAL ENTRIES: {mem_count} ===")
        r = await db.execute(select(TradeMemory).order_by(TradeMemory.created_at.desc()).limit(20))
        mems = r.scalars().all()
        for m in mems:
            print(f"  [{m.source}] {m.symbol} {m.side or '-'} pnl={m.pnl_usdt:+.2f} ({m.pnl_pct:+.1f}%) result={m.trade_result} reason={m.close_reason} @{m.created_at}")

        # 5. Orders
        r = await db.execute(select(func.count(Order.id)))
        order_count = r.scalar()
        print(f"\n=== TOTAL ORDERS: {order_count} ===")

        # 6. Data consistency check
        print(f"\n=== DATA CONSISTENCY ===")
        # Check: wallet total_pnl should match sum of closed position PnL
        for w in wallets:
            print(f"  Wallet total_pnl: {w.total_pnl}")
            print(f"  Sum of closed PnL: {total_pnl}")
            diff = abs(float(w.total_pnl) - float(total_pnl))
            if diff > 0.01:
                print(f"  ⚠️ MISMATCH: diff = {diff:.4f}")
            else:
                print(f"  ✅ MATCHED")

        # Check: journal count vs closed positions
        print(f"  Journal entries: {mem_count}, Closed positions: {len(closed)}")
        # Account for system entries
        r = await db.execute(select(func.count(TradeMemory.id)).where(TradeMemory.source != "system"))
        trade_mem = r.scalar()
        print(f"  Trade journal (non-system): {trade_mem}")
        if trade_mem != len(closed):
            print(f"  ⚠️ MISMATCH: {trade_mem} journal entries vs {len(closed)} closed positions")
        else:
            print(f"  ✅ MATCHED")


asyncio.run(health_check())
