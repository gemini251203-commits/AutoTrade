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
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
import json
from loguru import logger
from sqlalchemy import select, desc

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.market import Kline
from app.core.time_utils import utc_now


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
    
    def calculate_ema(self, closes: List[float], period: int) -> Optional[float]:
        """计算 EMA (指数移动平均线)"""
        if len(closes) < period:
            return None
        k = 2 / (period + 1)
        ema_val = closes[0]
        for price in closes[1:]:
            ema_val = price * k + ema_val * (1 - k)
        return round(ema_val, 4)
    
    def calculate_bollinger(self, closes: List[float], period: int = 20, std_dev: float = 2.0) -> Optional[Dict]:
        """计算布林带"""
        if len(closes) < period:
            return None
        window = closes[-period:]
        middle = sum(window) / period
        variance = sum((x - middle) ** 2 for x in window) / period
        std = variance ** 0.5
        return {
            "upper": round(middle + std_dev * std, 4),
            "middle": round(middle, 4),
            "lower": round(middle - std_dev * std, 4),
            "width": round((2 * std_dev * std) / middle * 100, 4) if middle else 0,
        }
    
    def calculate_kdj(self, klines: List[Dict], k_period: int = 9, d_period: int = 3) -> Optional[Dict]:
        """计算 KDJ 指标"""
        if len(klines) < k_period:
            return None
        window = klines[-k_period:]
        highest = max(k["high"] for k in window)
        lowest = min(k["low"] for k in window)
        current_close = klines[-1]["close"]
        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (current_close - lowest) / (highest - lowest) * 100
        k_val = rsv
        d_val = k_val
        j_val = 3 * k_val - 2 * d_val
        return {
            "k": round(k_val, 2),
            "d": round(d_val, 2),
            "j": round(j_val, 2),
        }
    
    def calculate_obv(self, klines: List[Dict]) -> Optional[float]:
        """计算 OBV (能量潮)"""
        if len(klines) < 2:
            return None
        obv = 0.0
        for i in range(1, len(klines)):
            if klines[i]["close"] > klines[i-1]["close"]:
                obv += klines[i]["volume"]
            elif klines[i]["close"] < klines[i-1]["close"]:
                obv -= klines[i]["volume"]
        return round(obv, 2)
    
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
            包含完整指标集的字典，所有指标名称均为扁平化 key
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
                "updated_at": utc_now().isoformat(),
            }
        
        # 提取收盘价和成交量
        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        
        # ── 基础指标 ──
        rsi = self.calculate_rsi(closes)
        macd = self.calculate_macd(closes)
        ma = self.calculate_ma(closes)
        atr = self.calculate_atr(klines)
        volume_ratio = self.calculate_volume_change(volumes)
        
        # ── 新增指标 ──
        ema_5  = self.calculate_ema(closes, 5)
        ema_10 = self.calculate_ema(closes, 10)
        ema_20 = self.calculate_ema(closes, 20)
        ema_50 = self.calculate_ema(closes, 50)
        ema_100 = self.calculate_ema(closes, 100)
        ema_144 = self.calculate_ema(closes, 144)  # Vegas Tunnel
        ema_169 = self.calculate_ema(closes, 169)  # Vegas Tunnel
        bollinger = self.calculate_bollinger(closes)
        kdj = self.calculate_kdj(klines)
        obv = self.calculate_obv(klines)
        
        # Volume Surge: 最近3根K线中最大的量比 (vs 20期均量)
        volume_surge = None
        if len(volumes) > 23:
            avg_vol_20 = sum(volumes[-21:-1]) / 20
            if avg_vol_20 > 0:
                recent_ratios = [volumes[-i] / avg_vol_20 for i in range(1, 4)]
                volume_surge = round(max(recent_ratios), 2)
        
        # 判断趋势 (用 EMA 交叉)
        trend = "neutral"
        if rsi and ema_20 and ema_50:
            current_price = closes[-1]
            if rsi > 50 and current_price > ema_20 > ema_50:
                trend = "bullish"
            elif rsi < 50 and current_price < ema_20 < ema_50:
                trend = "bearish"
        
        # 构建扁平化指标字典
        indicators = {
            # 动量
            "rsi": rsi,
            "macd": macd.get("macd") if macd else None,
            "macd_histogram": macd.get("histogram") if macd else None,
            "macd_signal": macd.get("signal") if macd else None,
            # 均线
            "ema_5": ema_5,
            "ema_10": ema_10,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_100": ema_100,
            "ema_144": ema_144,  # Vegas Tunnel
            "ema_169": ema_169,  # Vegas Tunnel
            **ma,  # ma7, ma25, ma99
            # 波动
            "atr": atr,
            # 量能
            "obv": obv,
            "volume_ratio": volume_ratio,
            "volume_surge": volume_surge,
        }
        
        # 布林带
        if bollinger:
            indicators["bollinger_upper"] = bollinger["upper"]
            indicators["bollinger_middle"] = bollinger["middle"]
            indicators["bollinger_lower"] = bollinger["lower"]
            indicators["bollinger_width"] = bollinger["width"]
        
        # KDJ
        if kdj:
            indicators["kdj_k"] = kdj["k"]
            indicators["kdj_d"] = kdj["d"]
            indicators["kdj_j"] = kdj["j"]
        
        result = {
            "symbol": symbol.upper(),
            "interval": interval,
            "current_price": closes[-1] if closes else None,
            "indicators": indicators,
            "trend": trend,
            "updated_at": utc_now().isoformat(),
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
        
        lines = [
            f"**{indicators['symbol']}** ({indicators['interval']}) 价格: ${price:,.2f} | 趋势: {trend_cn}",
            "",
            f"RSI(14): {ind.get('rsi', 'N/A')} | MACD: {ind.get('macd', 'N/A')} | 柱状: {ind.get('macd_histogram', 'N/A')}",
            f"EMA: 5={ind.get('ema_5', 'N/A')} | 10={ind.get('ema_10', 'N/A')} | 20={ind.get('ema_20', 'N/A')} | 50={ind.get('ema_50', 'N/A')}",
            f"Vegas Tunnel: EMA144={ind.get('ema_144', 'N/A')} | EMA169={ind.get('ema_169', 'N/A')}",
            f"ATR: {ind.get('atr', 'N/A')} | 量比: {ind.get('volume_ratio', 'N/A')}x | 量能脉冲: {ind.get('volume_surge', 'N/A')}x",
        ]
        
        if ind.get("bollinger_upper"):
            lines.append(f"布林: 上={ind['bollinger_upper']} | 中={ind['bollinger_middle']} | 下={ind['bollinger_lower']}")
        
        if ind.get("kdj_k") is not None:
            lines.append(f"KDJ: K={ind['kdj_k']} | D={ind['kdj_d']} | J={ind['kdj_j']}")
        
        return "\n".join(lines)


# ============================================================
# 可用指标白名单 (策略条件只能引用这些)
# ============================================================

AVAILABLE_INDICATORS = frozenset({
    # 动量
    "rsi", "macd", "macd_histogram", "macd_signal",
    # 均线
    "ema_5", "ema_10", "ema_20", "ema_50", "ema_100",
    "ema_144", "ema_169",  # Vegas Tunnel
    "ma7", "ma25", "ma99",
    # 波动
    "atr",
    "bollinger_upper", "bollinger_middle", "bollinger_lower", "bollinger_width",
    # 随机
    "kdj_k", "kdj_d", "kdj_j",
    # 量能
    "obv", "volume_ratio", "volume_surge",
    # 价位 (策略中常用的伪指标)
    "price", "close",
    "near_support", "near_resistance",
})


def validate_strategy_indicators(config: dict) -> list[str]:
    """
    校验策略配置中引用的指标是否都在白名单内
    
    Returns:
        错误列表 (空 = 全部通过)
    """
    errors = []
    for alpha in config.get("alphas", []):
        for cond in alpha.get("conditions", []):
            ind = cond.get("indicator", "")
            if ind and ind not in AVAILABLE_INDICATORS:
                errors.append(f"指标 '{ind}' 不可用")
    
    if errors:
        available = sorted(AVAILABLE_INDICATORS - {"price", "close", "near_support", "near_resistance"})
        errors.append(f"可用指标: {', '.join(available)}")
    
    return errors


# 全局单例
indicator_service = IndicatorService()
