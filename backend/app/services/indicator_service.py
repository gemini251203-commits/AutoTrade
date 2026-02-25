"""
Indicator Service - 閹垛偓閺堫垱瀵氶弽鍥吀缁犳婀囬崝?
======================================
娑?AI 閹绘劒绶甸幎鈧張顖涘瘹閺嶅洦鏆熼幑?

閸旂喕鍏?
1. 娴犲孩鏆熼幑顔肩氨鐠囪褰?K 缁炬寧鏆熼幑?
2. 鐠侊紕鐣婚幎鈧張顖涘瘹閺?(RSI, MACD, MA, ATR)
3. 缂傛挸鐡ㄩ崚?Redis 娓?AI 鐠嬪啰鏁?
4. 閸欘垱澧跨仦鏇熺仸閺嬪嫸绱濇笟澶哥艾濞ｈ濮為弴鏉戭樋閹稿洦鐖?

閹稿洦鐖ｉ崚妤勩€?
- RSI(14): 閻╃顕鍝勬€ラ幐鍥ㄦ殶
- MACD(12,26,9): 鐡掑濞嶉幐鍥ㄧ垼
- MA(7,25,99): 缁夎濮╅崸鍥╁殠
- ATR(14): 閻喎鐤勫▔銏犵畽
- Volume Change: 閹存劒姘﹂柌蹇撳綁閸栨牜宸?

閳跨媴绗?娓氭繆绂? pandas, numpy
"""

import asyncio
from decimal import Decimal
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

import redis.asyncio as redis
import json
from loguru import logger
from sqlalchemy import select, desc

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.market import Kline


class IndicatorService:
    """
    閹垛偓閺堫垱瀵氶弽鍥吀缁犳婀囬崝?
    
    鐠侊紕鐣婚獮鍓佺处鐎涙ɑ濡ч張顖涘瘹閺嶅浄绱濇笟?AI 閸掑棙鐎芥担璺ㄦ暏
    """
    
    # Redis Key 閸撳秶绱?
    REDIS_KEY_PREFIX = "autotrade:indicators:"
    
    # 閹稿洦鐖ｇ紓鎾崇摠閺冨爼妫?(缁?
    CACHE_TTL = 300  # 5閸掑棝鎸?
    
    # 姒涙顓婚崨銊︽埂
    DEFAULT_INTERVAL = "1h"
    
    def __init__(self):
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
    
    async def get_klines(
        self, 
        symbol: str, 
        interval: str = "1h", 
        limit: int = 100
    ) -> List[Dict]:
        """
        娴犲孩鏆熼幑顔肩氨閼惧嘲褰?K 缁炬寧鏆熼幑顕嗙礉閺佺増宓佹惔鎾茶礋缁岀儤妞?fallback 閸?Binance API
        
        Returns:
            List of kline dicts with: open, high, low, close, volume
        """
        # 1. 娴兼ê鍘涙禒搴㈡殶閹诡喖绨遍懢宄板絿
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Kline)
                .where(Kline.symbol == symbol.upper())
                .where(Kline.interval == interval)
                .order_by(desc(Kline.open_time))
                .limit(limit)
            )
            klines = result.scalars().all()
            
            if klines:
                data = []
                for k in reversed(klines):
                    data.append({
                        "open_time": k.open_time,
                        "open": float(k.open),
                        "high": float(k.high),
                        "low": float(k.low),
                        "close": float(k.close),
                        "volume": float(k.volume),
                    })
                return data
        
        # 2. 閺佺増宓佹惔鎾存￥閺佺増宓?閳?fallback 閸?Binance API
        try:
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            raw_klines = await client.get_klines(symbol.upper(), interval, limit=limit)
            if raw_klines:
                logger.info(f"[Indicator] DB empty, fetched {len(raw_klines)} klines from Binance API for {symbol}/{interval}")
                data = []
                for k in raw_klines:
                    data.append({
                        "open_time": k["open_time"],
                        "open": float(k["open"]),
                        "high": float(k["high"]),
                        "low": float(k["low"]),
                        "close": float(k["close"]),
                        "volume": float(k["volume"]),
                    })
                return data
        except Exception as e:
            logger.warning(f"[Indicator] Binance API fallback failed: {e}")
        
        return []
    
    def calculate_rsi(self, closes: List[float], period: int = 14) -> Optional[float]:
        """
        鐠侊紕鐣?RSI (閻╃顕鍝勬€ラ幐鍥ㄦ殶)
        
        RSI = 100 - (100 / (1 + RS))
        RS = 楠炲啿娼庢稉濠冨畾 / 楠炲啿娼庢稉瀣┘
        """
        if len(closes) < period + 1:
            return None
        
        # 鐠侊紕鐣绘禒閿嬬壐閸欐ê瀵?
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        # 閸掑棛顬囨稉濠冨畾閸滃奔绗呯捄?
        gains = [c if c > 0 else 0 for c in changes]
        losses = [-c if c < 0 else 0 for c in changes]
        
        # 鐠侊紕鐣婚獮鍐叉綆 (娴ｈ法鏁ら張鈧潻?period 娑?
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return round(rsi, 2)
    
    def calculate_macd(
        self, 
        closes: List[float], 
        fast: int = 12, 
        slow: int = 26, 
        signal: int = 9
    ) -> Optional[Dict]:
        """
        鐠侊紕鐣?MACD
        
        Returns:
            {"macd": float, "signal": float, "histogram": float}
        """
        if len(closes) < slow + signal:
            return None
        
        def ema(data: List[float], period: int) -> float:
            """閹稿洦鏆熺粔璇插З楠炲啿娼?""
            k = 2 / (period + 1)
            ema_val = data[0]
            for price in data[1:]:
                ema_val = price * k + ema_val * (1 - k)
            return ema_val
        
        # 鐠侊紕鐣昏箛顐ｅ弮 EMA
        ema_fast = ema(closes[-fast-signal:], fast)
        ema_slow = ema(closes[-slow-signal:], slow)
        
        macd_line = ema_fast - ema_slow
        
        # 缁犫偓閸? 娴ｈ法鏁ら張鈧崥搴濈娑?MACD 閸婇棿缍旀稉杞颁繆閸欓鍤庢导鎵暬
        signal_line = macd_line * 0.9  # 缁犫偓閸栨牕顦╅悶?
        histogram = macd_line - signal_line
        
        return {
            "macd": round(macd_line, 4),
            "signal": round(signal_line, 4),
            "histogram": round(histogram, 4),
        }
    
    def calculate_ma(self, closes: List[float], periods: List[int] = [7, 25, 99]) -> Dict[str, Optional[float]]:
        """
        鐠侊紕鐣荤粔璇插З閸у洨鍤?
        
        Returns:
            {"ma7": float, "ma25": float, "ma99": float}
        """
        result = {}
        for period in periods:
            if len(closes) >= period:
                ma = sum(closes[-period:]) / period
                result[f"ma{period}"] = round(ma, 2)
            else:
                result[f"ma{period}"] = None
        return result
    
    def calculate_atr(self, klines: List[Dict], period: int = 14) -> Optional[float]:
        """
        鐠侊紕鐣?ATR (楠炲啿娼庨惇鐔风杽濞夈垹绠?
        
        閻劋绨銏″疮鐠佸墽鐤?
        """
        if len(klines) < period + 1:
            return None
        
        true_ranges = []
        for i in range(1, len(klines)):
            high = klines[i]["high"]
            low = klines[i]["low"]
            prev_close = klines[i-1]["close"]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        atr = sum(true_ranges[-period:]) / period
        return round(atr, 4)
    
    def calculate_volume_change(self, volumes: List[float], period: int = 5) -> Optional[float]:
        """
        鐠侊紕鐣婚幋鎰唉闁插繐褰夐崠鏍芳 (闁插繑鐦?
        
        瑜版挸澧犻幋鎰唉闁?/ 鏉╁洤骞?N 閺堢喎閽╅崸鍥ㄥ灇娴溿倝鍣?
        """
        if len(volumes) < period + 1:
            return None
        
        avg_volume = sum(volumes[-period-1:-1]) / period
        if avg_volume == 0:
            return None
        
        current_volume = volumes[-1]
        ratio = current_volume / avg_volume
        
        return round(ratio, 2)
    
    async def calculate_all(
        self, 
        symbol: str, 
        interval: str = "1h"
    ) -> Dict[str, Any]:
        """
        鐠侊紕鐣婚幍鈧張澶嬪Η閺堫垱瀵氶弽?
        
        Returns:
            {
                "symbol": "BTCUSDT",
                "interval": "1h",
                "indicators": {
                    "rsi": 55.2,
                    "macd": {...},
                    "ma7": 77000.0,
                    "ma25": 76500.0,
                    "ma99": 75000.0,
                    "atr": 500.0,
                    "volume_ratio": 1.2,
                },
                "trend": "bullish" | "bearish" | "neutral",
                "updated_at": "2026-02-02T11:30:00"
            }
        """
        # 閼惧嘲褰?K 缁炬寧鏆熼幑?
        klines = await self.get_klines(symbol, interval, limit=100)
        
        if not klines:
            logger.warning(f"[Indicator] No klines for {symbol}/{interval}")
            return {
                "symbol": symbol,
                "interval": interval,
                "indicators": {},
                "trend": "unknown",
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
        
        # 閹绘劕褰囬弨鍓佹磸娴犲嘲鎷伴幋鎰唉闁?
        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        
        # 鐠侊紕鐣婚崥鍕€嶉幐鍥ㄧ垼
        rsi = self.calculate_rsi(closes)
        macd = self.calculate_macd(closes)
        ma = self.calculate_ma(closes)
        atr = self.calculate_atr(klines)
        volume_ratio = self.calculate_volume_change(volumes)
        
        # 閸掋倖鏌囩搾瀣◢
        trend = "neutral"
        if rsi and ma.get("ma7") and ma.get("ma25"):
            current_price = closes[-1]
            if rsi > 50 and current_price > ma["ma7"] > ma["ma25"]:
                trend = "bullish"
            elif rsi < 50 and current_price < ma["ma7"] < ma["ma25"]:
                trend = "bearish"
        
        result = {
            "symbol": symbol.upper(),
            "interval": interval,
            "current_price": closes[-1] if closes else None,
            "indicators": {
                "rsi": rsi,
                "macd": macd,
                **ma,
                "atr": atr,
                "volume_ratio": volume_ratio,
            },
            "trend": trend,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        
        # 缂傛挸鐡ㄩ崚?Redis
        try:
            r = await self._get_redis()
            key = f"{self.REDIS_KEY_PREFIX}{symbol.upper()}:{interval}"
            await r.setex(key, self.CACHE_TTL, json.dumps(result))
            logger.debug(f"[Indicator] Cached indicators for {symbol}/{interval}")
        except Exception as e:
            logger.warning(f"[Indicator] Redis cache error: {e}")
        
        return result
    
    async def get_cached(self, symbol: str, interval: str = "1h") -> Optional[Dict]:
        """
        閼惧嘲褰囩紓鎾崇摠閻ㄥ嫭瀵氶弽?(婵″倹鐏夌€涙ê婀?
        """
        try:
            r = await self._get_redis()
            key = f"{self.REDIS_KEY_PREFIX}{symbol.upper()}:{interval}"
            data = await r.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning(f"[Indicator] Redis get error: {e}")
        return None
    
    async def get_or_calculate(self, symbol: str, interval: str = "1h") -> Dict:
        """
        閼惧嘲褰囬幐鍥ㄧ垼 (娴兼ê鍘涚紓鎾崇摠閿涘苯鎯侀崚娆掝吀缁?
        """
        cached = await self.get_cached(symbol, interval)
        if cached:
            return cached
        return await self.calculate_all(symbol, interval)
    
    def format_for_ai(self, indicators: Dict) -> str:
        """
        閺嶇厧绱￠崠鏍ㄥ瘹閺嶅洦鏆熼幑顔昏礋 AI 閸欘垵顕伴惃鍕瀮閺?
        """
        if not indicators.get("indicators"):
            return f"閺嗗倹妫?{indicators.get('symbol', 'Unknown')} 閻ㄥ嫭濡ч張顖涘瘹閺嶅洦鏆熼幑顔衡偓?
        
        ind = indicators["indicators"]
        trend = indicators.get("trend", "unknown")
        price = indicators.get("current_price", 0)
        
        trend_cn = {"bullish": "閻瀹?, "bearish": "閻绌?, "neutral": "娑擃厽鈧?}.get(trend, "閺堫亞鐓?)
        
        text = f"""
**{indicators['symbol']} 閹垛偓閺堫垰鍨庨弸?* (閸涖劍婀? {indicators['interval']})

瑜版挸澧犳禒閿嬬壐: ${price:,.2f}
鐡掑濞嶉崚銈嗘焽: {trend_cn}

閹稿洦鐖ｉ弫鐗堝祦:
- RSI(14): {ind.get('rsi', 'N/A')} {'(鐡掑懍鎷?' if ind.get('rsi', 0) > 70 else '(鐡掑懎宕?' if ind.get('rsi', 0) < 30 else ''}
- MA7: ${ind.get('ma7', 0):,.2f}
- MA25: ${ind.get('ma25', 0):,.2f}
- MA99: ${ind.get('ma99', 0):,.2f}
- ATR(14): ${ind.get('atr', 0):,.4f}
- 閹存劒姘﹂柌蹇旂槷: {ind.get('volume_ratio', 'N/A')}x
"""
        
        if ind.get("macd"):
            macd = ind["macd"]
            text += f"- MACD: {macd.get('macd', 0):+.4f}\n"
        
        return text.strip()


# 閸忋劌鐪崡鏇氱伐
indicator_service = IndicatorService()
