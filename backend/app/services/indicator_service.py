"""
Indicator Service - 技术指标计算服务
======================================
为 AI 提供技术指标数据

功能:
1. 从数据库读取 K 线数据
2. 计算技术指标 (RSI, MACD, MA, ATR)
3. 缓存到 Redis 供 AI 调用
4. 可扩展架构，便于添加更多指标

指标列表:
- RSI(14): 相对强弱指数
- MACD(12,26,9): 趋势指标
- MA(7,25,99): 移动均线
- ATR(14): 真实波幅
- Volume Change: 成交量变化率

⚠️ 依赖: pandas, numpy
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
    技术指标计算服务
    
    计算并缓存技术指标，供 AI 分析使用
    """
    
    # Redis Key 前缀
    REDIS_KEY_PREFIX = "autotrade:indicators:"
    
    # 指标缓存时间 (秒)
    CACHE_TTL = 300  # 5分钟
    
    # 默认周期
    DEFAULT_INTERVAL = "1h"
    
    def __init__(self):
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
    
    async def get_klines(
        self, 
        symbol: str, 
        interval: str = "1h", 
        limit: int = 100
    ) -> List[Dict]:
        """
        从数据库获取 K 线数据，数据库为空时 fallback 到 Binance API
        
        Returns:
            List of kline dicts with: open, high, low, close, volume
        """
        # 1. 优先从数据库获取
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
        
        # 2. 数据库无数据 → fallback 到 Binance API
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
        计算 RSI (相对强弱指数)
        
        RSI = 100 - (100 / (1 + RS))
        RS = 平均上涨 / 平均下跌
        """
        if len(closes) < period + 1:
            return None
        
        # 计算价格变化
        changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        
        # 分离上涨和下跌
        gains = [c if c > 0 else 0 for c in changes]
        losses = [-c if c < 0 else 0 for c in changes]
        
        # 计算平均 (使用最近 period 个)
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
        计算 MACD
        
        Returns:
            {"macd": float, "signal": float, "histogram": float}
        """
        if len(closes) < slow + signal:
            return None
        
        def ema(data: List[float], period: int) -> float:
            """指数移动平均"""
            k = 2 / (period + 1)
            ema_val = data[0]
            for price in data[1:]:
                ema_val = price * k + ema_val * (1 - k)
            return ema_val
        
        # 计算快慢 EMA
        ema_fast = ema(closes[-fast-signal:], fast)
        ema_slow = ema(closes[-slow-signal:], slow)
        
        macd_line = ema_fast - ema_slow
        
        # 简化: 使用最后一个 MACD 值作为信号线估算
        signal_line = macd_line * 0.9  # 简化处理
        histogram = macd_line - signal_line
        
        return {
            "macd": round(macd_line, 4),
            "signal": round(signal_line, 4),
            "histogram": round(histogram, 4),
        }
    
    def calculate_ma(self, closes: List[float], periods: List[int] = [7, 25, 99]) -> Dict[str, Optional[float]]:
        """
        计算移动均线
        
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
        计算 ATR (平均真实波幅)
        
        用于止损设置
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
        计算成交量变化率 (量比)
        
        当前成交量 / 过去 N 期平均成交量
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
        计算所有技术指标
        
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
        # 获取 K 线数据
        klines = await self.get_klines(symbol, interval, limit=100)
        
        if not klines:
            logger.warning(f"[Indicator] No klines for {symbol}/{interval}")
            return {
                "symbol": symbol,
                "interval": interval,
                "indicators": {},
                "trend": "unknown",
                "updated_at": datetime.utcnow().isoformat(),
            }
        
        # 提取收盘价和成交量
        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        
        # 计算各项指标
        rsi = self.calculate_rsi(closes)
        macd = self.calculate_macd(closes)
        ma = self.calculate_ma(closes)
        atr = self.calculate_atr(klines)
        volume_ratio = self.calculate_volume_change(volumes)
        
        # 判断趋势
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
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        # 缓存到 Redis
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
        获取缓存的指标 (如果存在)
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
        获取指标 (优先缓存，否则计算)
        """
        cached = await self.get_cached(symbol, interval)
        if cached:
            return cached
        return await self.calculate_all(symbol, interval)
    
    def format_for_ai(self, indicators: Dict) -> str:
        """
        格式化指标数据为 AI 可读的文本
        """
        if not indicators.get("indicators"):
            return f"暂无 {indicators.get('symbol', 'Unknown')} 的技术指标数据。"
        
        ind = indicators["indicators"]
        trend = indicators.get("trend", "unknown")
        price = indicators.get("current_price", 0)
        
        trend_cn = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(trend, "未知")
        
        text = f"""
**{indicators['symbol']} 技术分析** (周期: {indicators['interval']})

当前价格: ${price:,.2f}
趋势判断: {trend_cn}

指标数据:
- RSI(14): {ind.get('rsi', 'N/A')} {'(超买)' if ind.get('rsi', 0) > 70 else '(超卖)' if ind.get('rsi', 0) < 30 else ''}
- MA7: ${ind.get('ma7', 0):,.2f}
- MA25: ${ind.get('ma25', 0):,.2f}
- MA99: ${ind.get('ma99', 0):,.2f}
- ATR(14): ${ind.get('atr', 0):,.4f}
- 成交量比: {ind.get('volume_ratio', 'N/A')}x
"""
        
        if ind.get("macd"):
            macd = ind["macd"]
            text += f"- MACD: {macd.get('macd', 0):+.4f}\n"
        
        return text.strip()


# 全局单例
indicator_service = IndicatorService()
