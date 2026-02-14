"""
Strategy Engine Service
========================
策略执行引擎

职责:
- 读取 Redis 行情数据
- 执行交易策略
- 生成任务单
"""

from typing import Optional, Dict, Any, List
from decimal import Decimal
import redis.asyncio as redis
from loguru import logger

from app.core.config import settings


class StrategyEngine:
    """
    策略执行引擎
    
    数据流: Redis (行情) -> 策略计算 -> 任务单
    """
    
    REDIS_KEY_PREFIX = "autotrade:market:"
    
    def __init__(self):
        """初始化策略引擎"""
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
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取实时行情
        
        Args:
            symbol: 交易对 (例如 BTCUSDT)
        
        Returns:
            行情数据字典或 None
        """
        try:
            r = await self._get_redis()
            key = f"{self.REDIS_KEY_PREFIX}{symbol.upper()}"
            data = await r.hgetall(key)
            
            if not data:
                return None
            
            return {
                "symbol": data.get("symbol"),
                "price": Decimal(data.get("price", "0")),
                "price_change_pct": float(data.get("price_change_pct", "0")),
                "high": Decimal(data.get("high", "0")),
                "low": Decimal(data.get("low", "0")),
                "volume": Decimal(data.get("volume", "0")),
            }
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_all_tickers(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        获取多个交易对的行情
        
        Args:
            symbols: 交易对列表
        
        Returns:
            {symbol: ticker_data} 字典
        """
        result = {}
        for symbol in symbols:
            ticker = await self.get_ticker(symbol)
            if ticker:
                result[symbol] = ticker
        return result
    
    async def evaluate_signal(
        self,
        symbol: str,
        indicators: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        评估交易信号
        
        Args:
            symbol: 交易对
            indicators: 技术指标数据
        
        Returns:
            信号数据或 None
        """
        # 示例: 简单 RSI 策略
        rsi = indicators.get("rsi")
        if rsi is None:
            return None
        
        signal = None
        confidence = 0.0
        
        if rsi < 30:
            signal = "buy"
            confidence = min((30 - rsi) / 10, 1.0)  # 0-1
        elif rsi > 70:
            signal = "sell"
            confidence = min((rsi - 70) / 10, 1.0)
        
        if signal:
            return {
                "symbol": symbol,
                "signal": signal,
                "confidence": confidence,
                "reason": f"RSI={rsi:.2f}",
                "indicators": indicators,
            }
        
        return None
    
    async def close(self):
        """关闭连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None
