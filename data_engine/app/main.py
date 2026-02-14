"""
Data Engine - Main Entry Point
===============================
启动所有数据爬虫和处理器
"""

import asyncio
import os
import sys
from loguru import logger

# 添加 infrastructure 到 Python 路径
sys.path.insert(0, "/app/infrastructure")

from app.spiders import BinanceSpider
from app.config import settings


async def main():
    """主函数 - 启动数据引擎"""
    logger.info("=" * 50)
    logger.info("AutoTrade Data Engine Starting...")
    logger.info(f"Environment: {settings.env_type}")
    logger.info("=" * 50)
    
    # 创建爬虫实例
    binance_spider = BinanceSpider(
        symbols=settings.watched_symbols,
        redis_url=settings.redis_url,
    )
    
    # 启动爬虫任务
    tasks = [
        asyncio.create_task(binance_spider.run()),
    ]
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Data Engine shutting down...")
    except Exception as e:
        logger.exception(f"Data Engine error: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Data Engine stopped by user")
