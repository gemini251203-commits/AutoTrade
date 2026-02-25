"""
MarketCollector - 鐢倸婧€閺佺増宓侀柌鍥肠閺堝秴濮?
===================================
閸氬骸褰存潻鎰攽閻ㄥ嫭鏆熼幑顕€鍣伴梿鍡樻箛閸斺槄绱濈拹鐔荤煑:
1. 閸氼垰濮╅弮璺烘礀婵夘偄宸婚崣?K 缁炬寧鏆熼幑?
2. 鐎规碍妞傞懢宄板絿閺堚偓閺?K 缁?
3. 閸愭瑥鍙?PostgreSQL + 閹恒劑鈧?Redis

閳跨媴绗?閺佺増宓佹稉鈧懛瀛樷偓?
- 鐎涙顔岄崥宥勫▏閻劋绗呴崚鎺斿殠閺嶇厧绱?(open_time, 闂?openTime)
- 娴犻攱鐗告担璺ㄦ暏 Decimal 鐎涙顑佹稉?
- 閺冨爼妫块幋鍏呭▏閻劍顕犵粔?
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
    鐢倸婧€閺佺増宓侀柌鍥肠閸?
    
    閸旂喕鍏?
    1. 閸氬骸褰村顏嗗箚闁插洭娉?K 缁炬寧鏆熼幑?
    2. 閺€顖涘瘮婢舵艾绔电粔宥冣偓浣割樋閸涖劍婀?
    3. 閼奉亜濮╅崶鐐诧綖閸樺棗褰堕弫鐗堝祦
    4. 鐎圭偞妞傜悰灞惧剰閹恒劑鈧礁鍩?Redis
    """
    
    # 闁插洭娉﹂柊宥囩枂 - 9娑擃亙姘﹂弰鎾愁嚠
    SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "LTCUSDT", "DOGEUSDT", "ASTERUSDT", "XAUUSDT"
    ]
    INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    
    # 闁插洭娉︽０鎴犲芳 (缁?
    FETCH_INTERVAL = 60  # 濮ｅ繐鍨庨柦鐔煎櫚闂嗗棔绔村▎?
    
    # Redis 闁款喖澧犵紓鈧?
    REDIS_KEY_PREFIX = "autotrade:market:"
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client = BinanceClient()
        self._redis: Optional[redis.Redis] = None
    
    async def _get_redis(self) -> redis.Redis:
        """閼惧嘲褰?Redis 鏉╃偞甯?""
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def start(self):
        """閸氼垰濮╅柌鍥肠閸?""
        if self._running:
            logger.warning("[MarketCollector] Already running")
            return
        
        self._running = True
        logger.info("[MarketCollector] Starting...")
        
        # 閸氼垰濮╅崥搴″酱娴犺濮?
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[MarketCollector] Background task started")
    
    async def stop(self):
        """閸嬫粍顒涢柌鍥肠閸?""
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
        """娑撹鎯婇悳?""
        # 妫ｆ牗顐奸崥顖氬З閺冭泛娲栨繅顐㈠坊閸欏弶鏆熼幑?
        await self._backfill_all()
        
        # 濞ｅ崬瀹抽崶鐐诧綖閿涘牆顩ч弸婊冩儙閻㈩煉绱?
        from app.core.config import settings
        if settings.deep_backfill_enabled:
            try:
                await self._deep_backfill()
            except Exception as e:
                logger.error(f"[MarketCollector] Deep backfill error: {e}")
        
        # 閹镐胶鐢婚柌鍥肠
        while self._running:
            try:
                await self._fetch_all_latest()
                await asyncio.sleep(self.FETCH_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MarketCollector] Loop error: {e}")
                await asyncio.sleep(5)  # 閸戞椽鏁婇崥搴ｇ搼瀵?5 缁夋帡鍣哥拠?
    
    async def _backfill_all(self):
        """閸ョ偛锝為幍鈧張澶婄缁夊秶娈戦崢鍡楀蕉閺佺増宓?""
        logger.info("[MarketCollector] Starting backfill...")
        
        for symbol in self.SYMBOLS:
            for interval in self.INTERVALS:
                try:
                    await self._backfill_history(symbol, interval, limit=500)
                except Exception as e:
                    logger.error(f"[MarketCollector] Backfill failed {symbol} {interval}: {e}")
                
                # 闁灝鍘ょ拠閿嬬湴鏉╁洤鎻?
                await asyncio.sleep(0.5)
        
        logger.info("[MarketCollector] Backfill completed")
    
    async def _backfill_history(self, symbol: str, interval: str, limit: int = 500):
        """
        閸ョ偛锝為幐鍥х暰鐢胶顫掗崪灞芥噯閺堢喓娈戦崢鍡楀蕉閺佺増宓?
        
        Args:
            symbol: 娴溿倖妲楃€?
            interval: 閺冨爼妫块崨銊︽埂
            limit: 閸ョ偛锝為弫浼村櫤
        """
        logger.debug(f"[MarketCollector] Backfilling {symbol} {interval} x{limit}")
        
        # 娴犲骸绔电€瑰骞忛崣?K 缁?
        klines = await self._client.get_klines(symbol, interval, limit)
        
        if not klines:
            logger.warning(f"[MarketCollector] No klines returned for {symbol} {interval}")
            return
        
        # 娣囨繂鐡ㄩ崚鐗堟殶閹诡喖绨?
        await self._save_klines(symbol, interval, klines)
        
        logger.info(f"[MarketCollector] Backfilled {len(klines)} klines for {symbol} {interval}")
    
    async def _deep_backfill(self):
        """濞ｅ崬瀹抽崶鐐诧綖閸樺棗褰堕弫鐗堝祦閿涘牊瀵滈柊宥囩枂閸ョ偛锝為弴鎾毐閸涖劍婀￠敍?""
        from app.core.config import settings
        intervals = [s.strip() for s in settings.deep_backfill_intervals.split(",")]
        days = settings.deep_backfill_days
        
        logger.info(f"[DeepBackfill] 瀵偓婵绻佹惔锕€娲栨繅? {days}婢? 閸涖劍婀?{intervals}")
        
        for symbol in self.SYMBOLS:
            for interval in intervals:
                try:
                    await self._deep_backfill_symbol(symbol, interval, days)
                except Exception as e:
                    logger.error(f"[DeepBackfill] {symbol} {interval} 婢惰精瑙? {e}")
                await asyncio.sleep(0.3)
        
        logger.info("[DeepBackfill] 閴?濞ｅ崬瀹抽崶鐐诧綖鐎瑰本鍨?)
    
    async def _deep_backfill_symbol(self, symbol: str, interval: str, days: int):
        """濞ｅ崬瀹抽崶鐐诧綖閸楁洑閲滅敮浣侯潚閸滃苯鎳嗛張?""
        from datetime import timedelta
        import time as time_module
        
        target_start_ms = int((time_module.time() - days * 86400) * 1000)
        
        # 閺屻儴顕楅弫鐗堝祦鎼存挷鑵戝鍙夋箒閻ㄥ嫭娓堕弮鈺傛殶閹?
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
            logger.debug(f"[DeepBackfill] {symbol} {interval} 瀹稿弶婀佺搾鍐差檮閺佺増宓侀敍宀冪儲鏉?)
            return
        
        # 娴犲骸鍑￠張澶嬫付閺冣晜鏆熼幑顔兼倻閸撳秶鐐曟い?
        end_time_ms = earliest - 1 if earliest else int(time_module.time() * 1000)
        total_fetched = 0
        max_pages = 50  # 鐎瑰鍙忔稉濠囨
        page = 0
        
        while end_time_ms > target_start_ms and page < max_pages:
            page += 1
            
            klines = await self._client.get_klines(
                symbol, interval, limit=1000, end_time=end_time_ms
            )
            
            if not klines:
                logger.info(f"[DeepBackfill] {symbol} {interval} 閺冪姵娲挎径姘殶閹诡噯绱濆鎻掑煂鐏忚棄銇?)
                break
            
            await self._save_klines(symbol, interval, klines)
            total_fetched += len(klines)
            
            end_time_ms = klines[0]["open_time"] - 1
            
            await asyncio.sleep(0.5)
        
        if total_fetched > 0:
            logger.info(f"[DeepBackfill] 閴?{symbol} {interval} 閸ョ偛锝?{total_fetched} 閺?({days}婢?")
    
    async def _fetch_all_latest(self):
        """閼惧嘲褰囬幍鈧張澶婄缁夊秶娈戦張鈧弬鐗堟殶閹?""
        price_map = {}  # 閻劋绨搴ㄦ珦閻╂垶甯?
        
        for symbol in self.SYMBOLS:
            try:
                # 閼惧嘲褰囬張鈧弬鎷岊攽閹懎鑻熼幒銊┾偓浣稿煂 Redis
                ticker = await self._client.get_ticker(symbol)
                if ticker:
                    await self._push_to_redis(symbol, ticker)
                    
                    # 閹绘劕褰囪ぐ鎾冲娴犻攱鐗搁悽銊ょ艾鐠併垹宕熼幘顔兼値
                    current_price = Decimal(ticker.get("lastPrice", "0"))
                    if current_price > 0:
                        price_map[symbol] = current_price
                        
                        # 棣冩暉 濡偓閺屻儵妾烘禒宄板礋閺勵垰鎯侀崣顖涘灇娴?
                        async with AsyncSessionLocal() as db:
                            filled = await OrderExecutor.check_limit_orders(
                                db, symbol, current_price
                            )
                            
                            # 棣冩暉 缂冩垶鐗搁崶鐐剁殶: 闂勬劒鐜崡鏇熷灇娴溿倕鎮楃憴锕€褰傜純鎴炵壐缁涙牜鏆?
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
                            
                            # 棣冩暉 濡偓閺屻儲娼禒璺哄礋鐟欙箑褰?
                            triggered = await OrderExecutor.check_conditional_orders(
                                db, symbol, current_price
                            )
                            if triggered:
                                await db.commit()
                                logger.info(
                                    f"[MarketCollector] {len(triggered)} conditional orders triggered for {symbol}"
                                )
                
                # 閼惧嘲褰囬張鈧弬?K 缁?(閸欘亜褰囬張鈧弬?2 閺夆槄绱濈涵顔荤箽鐟曞棛娲婅ぐ鎾冲閸滃奔绗傛稉鈧弽?
                for interval in self.INTERVALS:
                    klines = await self._client.get_klines(symbol, interval, limit=2)
                    if klines:
                        await self._save_klines(symbol, interval, klines)
                    
                    # 闁灝鍘ょ拠閿嬬湴鏉╁洤鎻?
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"[MarketCollector] Fetch failed for {symbol}: {e}")
    
    async def _save_klines(self, symbol: str, interval: str, klines: List[dict]):
        """
        閹靛綊鍣烘穱婵嗙摠 K 缁惧灝鍩岄弫鐗堝祦鎼?(UPSERT 闁槒绶?
        
        娴ｈ法鏁?PostgreSQL 閻?ON CONFLICT DO UPDATE 闂冨弶顒涢柌宥咁槻閹绘帒鍙?
        """
        if not klines:
            return
        
        async with AsyncSessionLocal() as db:
            try:
                # 閺嬪嫬缂撻幍褰掑櫤 UPSERT 鐠囶厼褰?
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
                    constraint="uq_kline_unique",  # 閸烆垯绔寸痪锔芥将閸?
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
        閹恒劑鈧礁鐤勯弮鎯邦攽閹懎鍩?Redis
        
        Redis Hash 缂佹挻鐎?
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
                "updated_at": datetime.utcnow().isoformat() + "Z",
            })
            
            # 鐠佸墽鐤嗘潻鍥ㄦ埂閺冨爼妫?(5 閸掑棝鎸?閿涘矂妲诲銏ｇ箖閺堢喐鏆熼幑顔界暙閻?
            await r.expire(key, 300)
            
        except Exception as e:
            logger.warning(f"[MarketCollector] Redis push error: {e}")


# 閸忋劌鐪崡鏇氱伐
market_collector = MarketCollector()
