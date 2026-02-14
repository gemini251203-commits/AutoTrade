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

# 添加项目根目录到 Python 路径 (兼容本地和 Docker)
PROJECT_ROOT = Path(__file__).parent.parent
backend_path = PROJECT_ROOT / "backend"
if backend_path.exists():
    sys.path.insert(0, str(backend_path))  # 本地: D:\AutoTrade\backend
else:
    sys.path.insert(0, str(PROJECT_ROOT))  # Docker: /app

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
BINANCE_MAX_LIMIT = 1500  # 币安单次最多返回 1500 根 K 线

# 深度回填配置: 每个周期要回填多少天的历史数据
BACKFILL_DEPTH_DAYS = {
    "1m": 1,      # 1 天 ≈ 1,440 根
    "5m": 7,      # 7 天 ≈ 2,016 根
    "15m": 60,    # 60 天 ≈ 5,760 根
    "30m": 60,    # 60 天 ≈ 2,880 根
    "1h": 365,    # 1 年 ≈ 8,760 根
    "4h": 365,    # 1 年 ≈ 2,190 根
    "1d": 1095,   # 3 年 ≈ 1,095 根
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
        limit: int = 500,
        start_time: int = None,
    ) -> list[dict]:
        """
        获取 K 线数据
        
        Args:
            start_time: 起始时间戳 (毫秒), 用于分页获取
        
        Returns:
            List of kline dicts
        """
        try:
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
            }
            if start_time is not None:
                params["startTime"] = start_time
            
            response = await self.client.get(
                BINANCE_KLINES_ENDPOINT,
                params=params,
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
        """
        深度分页回填历史数据
        
        使用 startTime 参数分页获取，每次最多 1500 根，
        循环直到获取到当前时间的数据。
        """
        logger.info("[Spider] ========== 开始深度历史数据回填 ==========")
        
        now_ms = int(time.time() * 1000)
        total_inserted = 0
        
        for symbol in self.symbols:
            for interval, depth_days in BACKFILL_DEPTH_DAYS.items():
                # 计算起始时间 (从 N 天前开始)
                start_ms = now_ms - (depth_days * 24 * 60 * 60 * 1000)
                page = 0
                interval_total = 0
                
                logger.info(
                    f"[Spider] 🔄 回填 {symbol} {interval} "
                    f"(最近 {depth_days} 天, 起始 {datetime.fromtimestamp(start_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')})"
                )
                
                while start_ms < now_ms:
                    page += 1
                    klines = await self.fetch_klines(
                        symbol, interval,
                        limit=BINANCE_MAX_LIMIT,
                        start_time=start_ms,
                    )
                    
                    if not klines:
                        break  # 没有更多数据
                    
                    count = await self.upsert_klines(klines)
                    interval_total += count
                    
                    # 下一页: 从最后一根 K 线的 close_time + 1ms 开始
                    start_ms = klines[-1]["close_time"] + 1
                    
                    logger.info(
                        f"[Spider]   📄 第 {page} 页: +{count} 条 "
                        f"(至 {datetime.fromtimestamp(klines[-1]['close_time']/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')})"
                    )
                    
                    # 如果返回数量 < 请求数量，说明已到最新数据
                    if len(klines) < BINANCE_MAX_LIMIT:
                        break
                    
                    # 避免请求过快
                    await asyncio.sleep(0.3)
                
                total_inserted += interval_total
                logger.info(f"[Spider] ✅ {symbol} {interval}: 共 {interval_total} 条 ({page} 页)")
                
                # 周期之间间隔
                await asyncio.sleep(0.5)
        
        logger.info(f"[Spider] ========== 深度回填完成, 共 {total_inserted} 条 ==========")
    
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
