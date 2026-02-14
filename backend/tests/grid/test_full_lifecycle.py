"""Full lifecycle test: start grid -> verify orders -> stop grid -> verify cancellation"""
import asyncio
from decimal import Decimal
from app.db import AsyncSessionLocal
from app.models.grid_bot import GridBot
from app.models.order import Order, OrderStatus
from app.services.grid.strategy import GridStrategy
from sqlalchemy import select

async def test_full_lifecycle():
    async with AsyncSessionLocal() as db:
        print("="*60)
        print("STEP 1: Start Grid Bot")
        print("="*60)
        
        # Get the grid bot
        result = await db.execute(select(GridBot).where(GridBot.id == 1))
        bot = result.scalar_one_or_none()
        
        if not bot:
            print("No grid bot found!")
            return
        
        print(f"  Bot: {bot.name}, Status: {bot.status}")
        
        # Start the grid
        current_price = Decimal("78500")
        bot = await GridStrategy.start_grid(db, bot_id=1, current_price=current_price)
        await db.commit()
        
        print(f"  Started! New status: {bot.status}")
        
        # Verify grid_levels has order IDs
        print("\n" + "="*60)
        print("STEP 2: Verify grid_levels has order IDs")
        print("="*60)
        
        await db.refresh(bot)
        levels_with_orders = 0
        for level in (bot.grid_levels or []):
            buy_id = level.get("buy_order_id")
            if buy_id:
                levels_with_orders += 1
                print(f"  Level {level.get('level')}: buy_order_id={buy_id}")
        
        print(f"\n  Total levels with order IDs: {levels_with_orders}")
        
        # Check open orders count
        result = await db.execute(
            select(Order).where(Order.status == OrderStatus.OPEN, Order.user_id == bot.user_id)
        )
        open_orders = result.scalars().all()
        print(f"  Open orders in database: {len(open_orders)}")
        
        # Stop the grid
        print("\n" + "="*60)
        print("STEP 3: Stop Grid Bot")
        print("="*60)
        
        bot = await GridStrategy.stop_grid(db, bot_id=1, cancel_orders=True)
        await db.commit()
        
        print(f"  Stopped! New status: {bot.status}")
        
        # Verify orders are cancelled
        print("\n" + "="*60)
        print("STEP 4: Verify orders are cancelled")
        print("="*60)
        
        result = await db.execute(
            select(Order).where(Order.status == OrderStatus.OPEN, Order.user_id == bot.user_id)
        )
        remaining_open = result.scalars().all()
        print(f"  Remaining open orders: {len(remaining_open)}")
        
        result = await db.execute(
            select(Order).where(Order.status == OrderStatus.CANCELLED, Order.user_id == bot.user_id)
        )
        cancelled_orders = result.scalars().all()
        print(f"  Cancelled orders: {len(cancelled_orders)}")
        
        if len(remaining_open) == 0:
            print("\n✅ SUCCESS: All orders cancelled when grid stopped!")
        else:
            print(f"\n❌ FAIL: {len(remaining_open)} orders still open!")

if __name__ == "__main__":
    asyncio.run(test_full_lifecycle())
