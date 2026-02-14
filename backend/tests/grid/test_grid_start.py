"""Debug script to test grid bot start - no explicit begin()"""
import asyncio
from decimal import Decimal
from app.db import AsyncSessionLocal
from app.services.grid import GridStrategy
from app.models.grid_bot import GridBot

async def test_start_grid():
    async with AsyncSessionLocal() as db:
        try:
            # 先检查有没有可启动的网格
            from sqlalchemy import select
            result = await db.execute(select(GridBot))
            bots = result.scalars().all()
            
            print(f"=== Found {len(bots)} grid bot(s) ===")
            for bot in bots:
                print(f"  ID={bot.id}, Name={bot.name}, Status={bot.status}, Symbol={bot.symbol}")
            
            if not bots:
                print("No grid bots to start!")
                return
            
            # 尝试启动第一个
            bot = bots[0]
            print(f"\n=== Attempting to start grid bot #{bot.id} ===")
            print(f"  Current status: {bot.status}")
            print(f"  Symbol: {bot.symbol}")
            print(f"  Price range: [{bot.lower_price} - {bot.upper_price}]")
            
            current_price = Decimal("78500")  # 当前价格模拟
            print(f"  Current price: {current_price}")
            
            # 不使用 async with db.begin()，直接调用服务
            result_bot = await GridStrategy.start_grid(
                db=db,
                bot_id=bot.id,
                current_price=current_price,
            )
            
            # 手动提交
            await db.commit()
            
            print(f"\n✅ Grid bot started successfully!")
            print(f"  New status: {result_bot.status}")
            print(f"  Current level: {result_bot.current_level}")
                
        except Exception as e:
            await db.rollback()
            print(f"\n❌ Error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_start_grid())
