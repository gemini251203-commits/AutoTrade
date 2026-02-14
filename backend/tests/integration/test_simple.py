"""Simplified test - avoid circular imports by not importing strategy directly"""
import asyncio
import sys
sys.path.insert(0, '.')

async def test():
    # Delay imports 
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select
    
    async with AsyncSessionLocal() as db:
        # Import models first
        from app.models.grid_bot import GridBot
        from app.models.order import Order, OrderStatus
        
        # Then import strategy
        from app.services.grid.strategy import GridStrategy
        
        # Get bot
        result = await db.execute(select(GridBot).where(GridBot.id == 1))
        bot = result.scalar_one_or_none()
        
        if not bot:
            print("No grid bot!")
            return
        
        print(f"Bot status: {bot.status}")
        
        # Start
        from decimal import Decimal
        bot = await GridStrategy.start_grid(db, 1, Decimal("78500"))
        await db.commit()
        
        await db.refresh(bot)
        levels = bot.grid_levels or []
        print(f"Grid levels: {len(levels)}")
        
        orders_with_id = sum(1 for l in levels if l.get("buy_order_id"))
        print(f"Levels with buy_order_id: {orders_with_id}")
        
        # Stop
        bot = await GridStrategy.stop_grid(db, 1)
        await db.commit()
        
        # Check orders
        result = await db.execute(select(Order).where(Order.status == OrderStatus.OPEN))
        open_orders = result.scalars().all()
        print(f"Open orders remaining: {len(open_orders)}")
        
        result = await db.execute(select(Order).where(Order.status == OrderStatus.CANCELLED))
        cancelled = result.scalars().all()
        print(f"Cancelled orders: {len(cancelled)}")

if __name__ == "__main__":
    asyncio.run(test())
