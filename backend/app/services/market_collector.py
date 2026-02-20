"""
MarketCollector - 市场数据采集服务
===================================
后台运行的数据采集服务，负责:
1. 启动时回填历史 K 线数据
2. 定时获取最新 K 线
3. 写入 PostgreSQL + 推送 Redis

⚠️ 数据一致性:
- 字段名使用下划线格式 (open_time, 非 openTime)
- 价格使用 Decimal 字符串
- 时间戳使用毫秒
"""

import asyncio
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

import redis.asyncio as redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from loguru import logger

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.market import Kline
from app.services.exchange import BinanceClient
from app.services.trading import OrderExecutor


class MarketCollector:
    """
    市场数据采集器
    
    功能:
    1. 后台循环采集 K 线数据
    2. 支持多币种、多周期
    3. 自动回填历史数据
    4. 实时行情推送到 Redis
    """
    
    # 采集配置 - 9个交易对
    SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "LTCUSDT", "DOGEUSDT", "ASTERUSDT", "XAUUSDT"
    ]
    INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    
    # 采集频率 (秒)
    FETCH_INTERVAL = 60  # 每分钟采集一次
    
    # Redis 键前缀
    REDIS_KEY_PREFIX = "autotrade:market:"
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client = BinanceClient()
        self._redis: Optional[redis.Redis] = None
    
    async def _get_redis(self) -> redis.Redis:
        """获取 Redis 连接"""
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def start(self):
        """启动采集器"""
        if self._running:
            logger.warning("[MarketCollector] Already running")
            return
        
        self._running = True
        logger.info("[MarketCollector] Starting...")
        
        # 启动后台任务
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[MarketCollector] Background task started")
    
    async def stop(self):
        """停止采集器"""
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._redis:
            await self._redis.close()
            self._redis = None
        
        logger.info("[MarketCollector] Stopped")
    
    async def _run_loop(self):
        """主循环"""
        # 首次启动时回填历史数据
        await self._backfill_all()
        
        # 深度回填（如果启用）
        from app.core.config import settings
        if settings.deep_backfill_enabled:
            try:
                await self._deep_backfill()
            except Exception as e:
                logger.error(f"[MarketCollector] Deep backfill error: {e}")
        
        # 持续采集
        while self._running:
            try:
                await self._fetch_all_latest()
                await asyncio.sleep(self.FETCH_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MarketCollector] Loop error: {e}")
                await asyncio.sleep(5)  # 出错后等待 5 秒重试
    
    async def _backfill_all(self):
        """回填所有币种的历史数据"""
        logger.info("[MarketCollector] Starting backfill...")
        
        for symbol in self.SYMBOLS:
            for interval in self.INTERVALS:
                try:
                    await self._backfill_history(symbol, interval, limit=500)
                except Exception as e:
                    logger.error(f"[MarketCollector] Backfill failed {symbol} {interval}: {e}")
                
                # 避免请求过快
                await asyncio.sleep(0.5)
        
        logger.info("[MarketCollector] Backfill completed")
    
    async def _backfill_history(self, symbol: str, interval: str, limit: int = 500):
        """
        回填指定币种和周期的历史数据
        
        Args:
            symbol: 交易对
            interval: 时间周期
            limit: 回填数量
        """
        logger.debug(f"[MarketCollector] Backfilling {symbol} {interval} x{limit}")
        
        # 从币安获取 K 线
        klines = await self._client.get_klines(symbol, interval, limit)
        
        if not klines:
            logger.warning(f"[MarketCollector] No klines returned for {symbol} {interval}")
            return
        
        # 保存到数据库
        await self._save_klines(symbol, interval, klines)
        
        logger.info(f"[MarketCollector] Backfilled {len(klines)} klines for {symbol} {interval}")
    
    async def _deep_backfill(self):
        """深度回填历史数据（按配置回填更长周期）"""
        from app.core.config import settings
        intervals = [s.strip() for s in settings.deep_backfill_intervals.split(",")]
        days = settings.deep_backfill_days
        
        logger.info(f"[DeepBackfill] 开始深度回填: {days}天, 周期={intervals}")
        
        for symbol in self.SYMBOLS:
            for interval in intervals:
                try:
                    await self._deep_backfill_symbol(symbol, interval, days)
                except Exception as e:
                    logger.error(f"[DeepBackfill] {symbol} {interval} 失败: {e}")
                await asyncio.sleep(0.3)
        
        logger.info("[DeepBackfill] ✅ 深度回填完成")
    
    async def _deep_backfill_symbol(self, symbol: str, interval: str, days: int):
        """深度回填单个币种和周期"""
        from datetime import timedelta
        import time as time_module
        
        target_start_ms = int((time_module.time() - days * 86400) * 1000)
        
        # 查询数据库中已有的最早数据
        from sqlalchemy import select, func
        from app.models.market import Kline
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.min(Kline.open_time)).where(
                    Kline.symbol == symbol,
                    Kline.interval == interval,
                )
            )
            earliest = result.scalar()
        
        if earliest and earliest <= target_start_ms:
            logger.debug(f"[DeepBackfill] {symbol} {interval} 已有足够数据，跳过")
            return
        
        # 从已有最早数据向前翻页
        end_time_ms = earliest - 1 if earliest else int(time_module.time() * 1000)
        total_fetched = 0
        max_pages = 50  # 安全上限
        page = 0
        
        while end_time_ms > target_start_ms and page < max_pages:
            page += 1
            
            klines = await self._client.get_klines(
                symbol, interval, limit=1000, end_time=end_time_ms
            )
            
            if not klines:
                logger.info(f"[DeepBackfill] {symbol} {interval} 无更多数据，已到尽头")
                break
            
            await self._save_klines(symbol, interval, klines)
            total_fetched += len(klines)
            
            end_time_ms = klines[0]["open_time"] - 1
            
            await asyncio.sleep(0.5)
        
        if total_fetched > 0:
            logger.info(f"[DeepBackfill] ✅ {symbol} {interval} 回填 {total_fetched} 条 ({days}天)")
    
    async def _fetch_all_latest(self):
        """获取所有币种的最新数据"""
        price_map = {}  # 用于风险监控
        
        for symbol in self.SYMBOLS:
            try:
                # 获取最新行情并推送到 Redis
                ticker = await self._client.get_ticker(symbol)
                if ticker:
                    await self._push_to_redis(symbol, ticker)
                    
                    # 提取当前价格用于订单撮合
                    current_price = Decimal(ticker.get("lastPrice", "0"))
                    if current_price > 0:
                        price_map[symbol] = current_price
                        
                        # 🔥 检查限价单是否可成交
                        async with AsyncSessionLocal() as db:
                            filled = await OrderExecutor.check_limit_orders(
                                db, symbol, current_price
                            )
                            
                            # 🔥 网格回调: 限价单成交后触发网格策略
                            if filled:
                                from app.services.grid import GridStrategy
                                for order in filled:
                                    try:
                                        await GridStrategy.on_order_filled(db, order)
                                    except Exception as ge:
                                        logger.warning(f"[MarketCollector] Grid callback error: {ge}")
                                        
                                await db.commit()
                                logger.info(
                                    f"[MarketCollector] {len(filled)} limit orders filled for {symbol}"
                                )
                            
                            # 🔥 检查条件单触发
                            triggered = await OrderExecutor.check_conditional_orders(
                                db, symbol, current_price
                            )
                            if triggered:
                                await db.commit()
                                logger.info(
                                    f"[MarketCollector] {len(triggered)} conditional orders triggered for {symbol}"
                                )
                
                # 获取最新 K 线 (只取最新 2 条，确保覆盖当前和上一根)
                for interval in self.INTERVALS:
                    klines = await self._client.get_klines(symbol, interval, limit=2)
                    if klines:
                        await self._save_klines(symbol, interval, klines)
                    
                    # 避免请求过快
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"[MarketCollector] Fetch failed for {symbol}: {e}")
    
    async def _save_klines(self, symbol: str, interval: str, klines: List[dict]):
        """
        批量保存 K 线到数据库 (UPSERT 逻辑)
        
        使用 PostgreSQL 的 ON CONFLICT DO UPDATE 防止重复插入
        """
        if not klines:
            return
        
        async with AsyncSessionLocal() as db:
            try:
                # 构建批量 UPSERT 语句
                values = []
                for k in klines:
                    values.append({
                        "symbol": symbol,
                        "interval": interval,
                        "open_time": k["open_time"],
                        "open": Decimal(str(k["open"])),
                        "high": Decimal(str(k["high"])),
                        "low": Decimal(str(k["low"])),
                        "close": Decimal(str(k["close"])),
                        "volume": Decimal(str(k["volume"])),
                        "close_time": k.get("close_time"),
                        "quote_volume": Decimal(str(k.get("quote_volume", 0))) if k.get("quote_volume") else None,
                        "trades": k.get("trades"),
                    })
                
                # PostgreSQL UPSERT
                stmt = insert(Kline).values(values)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_kline_unique",  # 唯一约束名
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                        "close_time": stmt.excluded.close_time,
                        "quote_volume": stmt.excluded.quote_volume,
                        "trades": stmt.excluded.trades,
                        "updated_at": datetime.utcnow(),
                    }
                )
                
                await db.execute(stmt)
                await db.commit()
                
            except Exception as e:
                logger.error(f"[MarketCollector] Save klines error: {e}")
                await db.rollback()
    
    async def _push_to_redis(self, symbol: str, ticker: dict):
        """
        推送实时行情到 Redis
        
        Redis Hash 结构:
        autotrade:market:BTCUSDT -> {
            symbol: "BTCUSDT",
            price: "78000.0",
            price_change_pct: "2.5",
            high: "79000.0",
            low: "77000.0",
            volume: "12345.67",
            updated_at: "2026-02-01T08:45:00Z"
        }
        """
        try:
            r = await self._get_redis()
            key = f"{self.REDIS_KEY_PREFIX}{symbol}"
            
            await r.hset(key, mapping={
                "symbol": symbol,
                "price": ticker.get("lastPrice", "0"),
                "price_change_pct": ticker.get("priceChangePercent", "0"),
                "high": ticker.get("highPrice", "0"),
                "low": ticker.get("lowPrice", "0"),
                "volume": ticker.get("volume", "0"),
                "updated_at": datetime.utcnow().isoformat(),
            })
            
            # 设置过期时间 (5 分钟)，防止过期数据残留
            await r.expire(key, 300)
            
        except Exception as e:
            logger.warning(f"[MarketCollector] Redis push error: {e}")


# 全局单例
market_collector = MarketCollector()
