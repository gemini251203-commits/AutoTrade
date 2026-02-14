"""
K-line Redis Cache Service
============================
Redis 缓存层，加速 K 线数据查询

功能:
1. 缓存热门查询（减少 DB 压力）
2. 自动过期（数据不会陈旧）
3. Cache-aside 模式（查缓存 → miss 时查 DB → 写缓存）

缓存策略:
- 1m/5m 周期: 缓存 30 秒（高频更新）
- 15m/30m 周期: 缓存 2 分钟
- 1h/4h/1d 周期: 缓存 5 分钟

Redis Key 格式:
    autotrade:kline:{symbol}:{interval}:{limit}
"""

import json
from typing import Optional, List
from loguru import logger

import redis.asyncio as aioredis

from app.core.config import settings


# 缓存过期时间 (秒)
CACHE_TTL = {
    "1m": 30,
    "5m": 30,
    "15m": 120,
    "30m": 120,
    "1h": 300,
    "4h": 300,
    "1d": 300,
}

# Redis Key 前缀
KEY_PREFIX = "autotrade:kline:"


class KlineCache:
    """K 线数据缓存"""
    
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
    
    async def _get_redis(self) -> aioredis.Redis:
        """获取 Redis 连接"""
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    def _make_key(self, symbol: str, interval: str, limit: int) -> str:
        """生成缓存键"""
        return f"{KEY_PREFIX}{symbol}:{interval}:{limit}"
    
    async def get(self, symbol: str, interval: str, limit: int) -> Optional[dict]:
        """
        从缓存获取 K 线数据
        
        Returns:
            缓存的 KlineListResponse 字典，或 None
        """
        try:
            r = await self._get_redis()
            key = self._make_key(symbol, interval, limit)
            data = await r.get(key)
            
            if data:
                logger.debug(f"[KlineCache] HIT {symbol} {interval} x{limit}")
                return json.loads(data)
            
            logger.debug(f"[KlineCache] MISS {symbol} {interval} x{limit}")
            return None
            
        except Exception as e:
            # Redis 故障时跳过缓存 (fail-open)
            logger.warning(f"[KlineCache] Get error: {e}")
            return None
    
    async def set(self, symbol: str, interval: str, limit: int, data: dict):
        """
        写入缓存
        
        Args:
            data: KlineListResponse 字典
        """
        try:
            r = await self._get_redis()
            key = self._make_key(symbol, interval, limit)
            ttl = CACHE_TTL.get(interval, 60)
            
            await r.set(key, json.dumps(data), ex=ttl)
            logger.debug(f"[KlineCache] SET {symbol} {interval} x{limit} (TTL={ttl}s)")
            
        except Exception as e:
            logger.warning(f"[KlineCache] Set error: {e}")
    
    async def invalidate(self, symbol: str, interval: str):
        """
        清除指定交易对和周期的所有缓存
        
        在收到新数据时调用
        """
        try:
            r = await self._get_redis()
            pattern = f"{KEY_PREFIX}{symbol}:{interval}:*"
            
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=100)
                if keys:
                    await r.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            
            if deleted:
                logger.debug(f"[KlineCache] Invalidated {deleted} keys for {symbol} {interval}")
                
        except Exception as e:
            logger.warning(f"[KlineCache] Invalidate error: {e}")
    
    async def close(self):
        """关闭连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None


# 全局单例
kline_cache = KlineCache()
