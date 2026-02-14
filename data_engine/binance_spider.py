#!/usr/bin/env python3
"""
Binance Data Spider
====================
币安 USDT 合约 K 线数据爬虫

功能:
1. 历史回填 (Backfill): 启动时抓取各周期最近 500+ 根 K 线
2. 实时更新 (Real-time): 每 2 秒更新最新 K 线
3. Upsert 逻辑: 时间戳存在则更新，不存在则插入

运行方式:
    cd backend
    python -m data_engine.binance_spider

或直接:
    python data_engine/binance_spider.py
"""

import os
import sys
import time
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import httpx
from loguru import logger
from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO",
)

# 币安合约 API
BINANCE_FAPI_BASE = "https://fapi.binance.com"
BINANCE_KLINES_ENDPOINT = "/fapi/v1/klines"

# 支持的时间周期及对应的回填数量
INTERVALS = {
    "1m": 500,   # 500 根 1 分钟 K 线 ≈ 8.3 小时
    "5m": 500,   # 500 根 5 分钟 K 线 ≈ 41.6 小时
    "15m": 500,  # 500 根 15 分钟 K 线 ≈ 5.2 天
    "30m": 500,  # 500 根 30 分钟 K 线 ≈ 10.4 天
    "1h": 720,   # 720 根 1 小时 K 线 ≈ 30 天
    "4h": 720,   # 720 根 4 小时 K 线 ≈ 120 天
    "1d": 1095,  # 1095 根日 K 线 ≈ 3 年
}

# 默认交易对
DEFAULT_SYMBOLS = ["BTCUSDT"]


class BinanceSpider:
    """币安 K 线数据爬虫"""
    
    def __init__(self, symbols: list[str] = None, proxy: str = None):
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.proxy = proxy or os.getenv("HTTP_PROXY")
        self.client: httpx.AsyncClient = None
        self.db_session = None
        
    async def init(self):
        """初始化 HTTP 客户端和数据库连接"""
        # HTTP 客户端
        transport = None
        if self.proxy:
            transport = httpx.AsyncHTTPTransport(proxy=self.proxy)
            logger.info(f"[Spider] 使用代理: {self.proxy}")
        
        self.client = httpx.AsyncClient(
            base_url=BINANCE_FAPI_BASE,
            transport=transport,
            timeout=30.0,
        )
        
        # 数据库连接
        from app.db.session import AsyncSessionLocal
        self.db_session = AsyncSessionLocal
        
        logger.info(f"[Spider] 初始化完成, 监控币种: {', '.join(self.symbols)}")
        
    async def close(self):
        """关闭连接"""
        if self.client:
            await self.client.aclose()
            
    async def fetch_klines(
        self, 
        symbol: str, 
        interval: str, 
        limit: int = 500
    ) -> list[dict]:
        """
        获取 K 线数据
        
        Returns:
            List of kline dicts with keys: open_time, open, high, low, close, volume, ...
        """
        try:
            response = await self.client.get(
                BINANCE_KLINES_ENDPOINT,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                }
            )
            response.raise_for_status()
            raw_data = response.json()
            
            # 解析币安 K 线格式
            # [open_time, open, high, low, close, volume, close_time, quote_volume, trades, ...]
            klines = []
            for item in raw_data:
                klines.append({
                    "symbol": symbol,
                    "interval": interval,
                    "open_time": item[0],
                    "open": Decimal(str(item[1])),
                    "high": Decimal(str(item[2])),
                    "low": Decimal(str(item[3])),
                    "close": Decimal(str(item[4])),
                    "volume": Decimal(str(item[5])),
                    "close_time": item[6],
                    "quote_volume": Decimal(str(item[7])),
                    "trades": item[8],
                })
            
            return klines
            
        except Exception as e:
            logger.error(f"[Spider] 获取 K 线失败 {symbol} {interval}: {e}")
            return []
    
    async def upsert_klines(self, klines: list[dict]):
        """
        Upsert K 线数据到数据库
        
        使用 ON CONFLICT DO UPDATE 实现:
        - 时间戳不存在: 插入新记录
        - 时间戳已存在: 更新 OHLCV 数据
        """
        if not klines:
            return 0
            
        from app.models.market import Kline
        
        async with self.db_session() as db:
            try:
                # 检测数据库类型
                db_url = str(db.get_bind().url)
                
                if "postgresql" in db_url:
                    # PostgreSQL: 使用 ON CONFLICT DO UPDATE
                    stmt = pg_insert(Kline).values(klines)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['symbol', 'interval', 'open_time'],
                        set_={
                            'open': stmt.excluded.open,
                            'high': stmt.excluded.high,
                            'low': stmt.excluded.low,
                            'close': stmt.excluded.close,
                            'volume': stmt.excluded.volume,
                            'close_time': stmt.excluded.close_time,
                            'quote_volume': stmt.excluded.quote_volume,
                            'trades': stmt.excluded.trades,
                            'updated_at': datetime.utcnow(),
                        }
                    )
                else:
                    # SQLite: 使用 ON CONFLICT DO REPLACE
                    stmt = sqlite_insert(Kline).values(klines)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['symbol', 'interval', 'open_time'],
                        set_={
                            'open': stmt.excluded.open,
                            'high': stmt.excluded.high,
                            'low': stmt.excluded.low,
                            'close': stmt.excluded.close,
                            'volume': stmt.excluded.volume,
                            'close_time': stmt.excluded.close_time,
                            'quote_volume': stmt.excluded.quote_volume,
                            'trades': stmt.excluded.trades,
                            'updated_at': datetime.utcnow(),
                        }
                    )
                
                await db.execute(stmt)
                await db.commit()
                return len(klines)
                
            except Exception as e:
                logger.error(f"[Spider] 数据库写入失败: {e}")
                await db.rollback()
                return 0
    
    async def backfill(self):
        """历史数据回填"""
        logger.info("[Spider] ========== 开始历史数据回填 ==========")
        
        total_inserted = 0
        
        for symbol in self.symbols:
            for interval, limit in INTERVALS.items():
                logger.info(f"[Spider] 回填 {symbol} {interval} (最近 {limit} 根)...")
                
                klines = await self.fetch_klines(symbol, interval, limit)
                
                if klines:
                    count = await self.upsert_klines(klines)
                    total_inserted += count
                    latest = klines[-1]
                    logger.info(
                        f"[Spider] ✅ {symbol} {interval}: {count} 条, "
                        f"最新价 ${float(latest['close']):,.2f}"
                    )
                else:
                    logger.warning(f"[Spider] ⚠️ {symbol} {interval}: 无数据")
                
                # 避免请求过快
                await asyncio.sleep(0.5)
        
        logger.info(f"[Spider] ========== 回填完成, 共 {total_inserted} 条 ==========")
    
    async def realtime_loop(self):
        """实时更新循环"""
        logger.info("[Spider] ========== 进入实时更新模式 ==========")
        
        while True:
            try:
                for symbol in self.symbols:
                    # 只更新 1m K 线 (最快频率)
                    klines = await self.fetch_klines(symbol, "1m", limit=1)
                    
                    if klines:
                        await self.upsert_klines(klines)
                        latest = klines[-1]
                        logger.info(
                            f"[Spider] {symbol} 1m 更新: ${float(latest['close']):,.2f} "
                            f"(H:{float(latest['high']):,.2f} L:{float(latest['low']):,.2f})"
                        )
                
                await asyncio.sleep(2)
                
            except KeyboardInterrupt:
                logger.info("[Spider] 收到中断信号, 退出...")
                break
            except Exception as e:
                logger.error(f"[Spider] 实时更新异常: {e}")
                await asyncio.sleep(5)
    
    async def run(self):
        """运行爬虫"""
        await self.init()
        
        try:
            # 1. 历史回填
            await self.backfill()
            
            # 2. 实时更新
            await self.realtime_loop()
            
        finally:
            await self.close()


async def main():
    """主入口"""
    logger.info("=" * 60)
    logger.info("🕷️  币安 K 线数据爬虫 v1.0")
    logger.info("=" * 60)
    
    # 从环境变量读取代理 (可选)
    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    
    # 创建爬虫实例
    spider = BinanceSpider(
        symbols=["BTCUSDT"],
        proxy=proxy,
    )
    
    await spider.run()


if __name__ == "__main__":
    asyncio.run(main())
