"""Fix alembic version table and apply column renames"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def main():
    async with AsyncSessionLocal() as db:
        # 1. Check current alembic versions
        r = await db.execute(text("SELECT version_num FROM alembic_version"))
        versions = [row[0] for row in r.fetchall()]
        print(f"Current versions: {versions}")

        # 2. Delete stale revision that no longer exists in code
        await db.execute(text("DELETE FROM alembic_version WHERE version_num = '5d866d4a35d4'"))
        print("Deleted stale revision 5d866d4a35d4")

        # 3. Check if columns need renaming
        r2 = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'grid_bots' AND column_name IN ('total_fee', 'total_commission')"
        ))
        grid_cols = [row[0] for row in r2.fetchall()]
        print(f"grid_bots fee columns: {grid_cols}")

        r3 = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'positions' AND column_name IN ('accumulated_funding_fee', 'total_funding_fee')"
        ))
        pos_cols = [row[0] for row in r3.fetchall()]
        print(f"positions funding columns: {pos_cols}")

        # 4. Rename if needed
        if "total_fee" in grid_cols and "total_commission" not in grid_cols:
            await db.execute(text("ALTER TABLE grid_bots RENAME COLUMN total_fee TO total_commission"))
            print("Renamed grid_bots.total_fee -> total_commission")
        else:
            print("grid_bots: no rename needed")

        if "accumulated_funding_fee" in pos_cols and "total_funding_fee" not in pos_cols:
            await db.execute(text("ALTER TABLE positions RENAME COLUMN accumulated_funding_fee TO total_funding_fee"))
            print("Renamed positions.accumulated_funding_fee -> total_funding_fee")
        else:
            print("positions: no rename needed")

        # 5. Stamp migration as done
        await db.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('u1n2i3f4y5f6') ON CONFLICT DO NOTHING"
        ))
        print("Stamped u1n2i3f4y5f6")

        await db.commit()

        # 6. Verify
        r4 = await db.execute(text("SELECT version_num FROM alembic_version"))
        print(f"Final versions: {[row[0] for row in r4.fetchall()]}")
        print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
