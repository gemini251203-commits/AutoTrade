"""Debug script to test grid bot creation"""
import asyncio
from decimal import Decimal
from app.db import AsyncSessionLocal
from app.services.grid import GridStrategy
from app.models.grid_bot import GridType, GridDirection

async def test_create_grid():
    async with AsyncSessionLocal() as db:
        try:
            async with db.begin():
                bot = await GridStrategy.create_grid_bot(
                    db=db,
                    user_id=1,  # Assuming user ID 1
                    name="Test Grid Bot",
                    symbol="BTCUSDT",
                    lower_price=Decimal("77200"),
                    upper_price=Decimal("79500"),
                    grid_count=10,
                    investment=Decimal("100"),
                    leverage=5,
                    grid_type=GridType.ARITHMETIC,
                    direction=GridDirection.NEUTRAL,
                    stop_loss_price=None,
                    take_profit_price=None,
                )
                print(f"✅ Grid bot created successfully! ID: {bot.id}")
        except Exception as e:
            print(f"❌ Error creating grid bot: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_create_grid())
