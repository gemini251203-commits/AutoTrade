"""
数据清理脚本
清空 klines 表以准备新的数据采集
"""
import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def truncate_klines():
    """清空 klines 表"""
    async with AsyncSessionLocal() as db:
        await db.execute(text("TRUNCATE TABLE klines"))
        await db.commit()
        print("✅ klines table truncated successfully")


if __name__ == "__main__":
    asyncio.run(truncate_klines())
