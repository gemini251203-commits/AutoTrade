"""Pre-fix verification + fix for frozen fund leaks"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    async with AsyncSessionLocal() as db:
        # CHECK: Active orders for User 1 and 5
        r = await db.execute(text("""
            SELECT id, user_id, status::text, symbol
            FROM orders
            WHERE user_id IN (1, 5) AND status::text IN ('pending', 'open')
        """))
        active_orders = r.fetchall()
        print(f"Active orders for User 1,5: {len(active_orders)}")
        for o in active_orders:
            print(f"  Order {o[0]}: user={o[1]} status={o[2]} {o[3]}")

        # CHECK: Open positions for User 1 and 5
        r2 = await db.execute(text("""
            SELECT id, user_id, status::text, symbol, side::text
            FROM positions
            WHERE user_id IN (1, 5) AND status::text = 'open'
        """))
        open_positions = r2.fetchall()
        print(f"Open positions for User 1,5: {len(open_positions)}")
        for p in open_positions:
            print(f"  Position {p[0]}: user={p[1]} {p[3]} {p[4]}")

        # Current wallet state
        r3 = await db.execute(text("""
            SELECT user_id, balance, frozen FROM wallets WHERE user_id IN (1, 5) ORDER BY user_id
        """))
        for w in r3.fetchall():
            print(f"BEFORE - User {w[0]}: balance={w[1]}, frozen={w[2]}")

        if mode == "fix":
            if active_orders or open_positions:
                print("ABORT: Active orders or positions exist! Cannot auto-fix.")
                return

            print("\nApplying fix: releasing stuck frozen funds...")
            await db.execute(text("""
                UPDATE wallets
                SET balance = balance + frozen, frozen = 0
                WHERE user_id IN (1, 5) AND frozen > 0
            """))
            await db.commit()

            # Verify after fix
            r4 = await db.execute(text("""
                SELECT user_id, balance, frozen FROM wallets WHERE user_id IN (1, 5) ORDER BY user_id
            """))
            for w in r4.fetchall():
                print(f"AFTER  - User {w[0]}: balance={w[1]}, frozen={w[2]}")

            print("\n✅ Fix applied successfully!")
        else:
            print("\nRun with 'fix' argument to apply: python scripts/fix_frozen.py fix")


if __name__ == "__main__":
    asyncio.run(main())
