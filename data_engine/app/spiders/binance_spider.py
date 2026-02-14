"""
Binance WebSocket Spider
=========================
连接 Binance WebSocket 获取实时行情数据
"""

import asyncio
import json
from typing import List, Optional
from loguru import logger
import redis.asyncio as redis

# 添加 infrastructure 支持
import sys
sys.path.insert(0, "/app/infrastructure")

try:
    from infrastructure.network import NetworkManager
except ImportError:
    NetworkManager = None


class BinanceSpider:
    """
    Binance 实时数据爬虫
    
    数据流: Binance WebSocket -> 清洗 -> Redis
    """
    
    # Binance WebSocket 基础 URL
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"
    FUTURES_WS_BASE_URL = "wss://fstream.binance.com/ws"
    
    # Redis Key 前缀
    REDIS_KEY_PREFIX = "autotrade:market:"
    
    def __init__(
        self,
        symbols: List[str],
        redis_url: str,
        use_futures: bool = True,
    ):
        """
        初始化 Binance 爬虫
        
        Args:
            symbols: 监控的交易对列表
            redis_url: Redis 连接 URL
            use_futures: 是否使用期货数据
        """
        self.symbols = [s.lower() for s in symbols]
        self.redis_url = redis_url
        self.use_futures = use_futures
        self._redis: Optional[redis.Redis] = None
        self._running = False
    
    @property
    def stream_url(self) -> str:
        """
        构建 WebSocket 流 URL
        
        格式: wss://stream.binance.com:9443/ws/btcusdt@ticker/ethusdt@ticker
        """
        base = self.FUTURES_WS_BASE_URL if self.use_futures else self.WS_BASE_URL
        streams = "/".join([f"{s}@ticker" for s in self.symbols])
        return f"{base}/{streams}"
    
    async def _get_redis(self) -> redis.Redis:
        """获取 Redis 连接"""
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis
    
    async def _save_ticker(self, data: dict) -> None:
        """
        保存 Ticker 数据到 Redis
        
        Args:
            data: Binance ticker 数据
        """
        try:
            symbol = data.get("s", "").upper()
            if not symbol:
                return
            
            # 构建简化的 ticker 数据
            ticker = {
                "symbol": symbol,
                "price": data.get("c", "0"),           # 最新价
                "price_change": data.get("p", "0"),    # 24h 价格变化
                "price_change_pct": data.get("P", "0"), # 24h 价格变化百分比
                "high": data.get("h", "0"),            # 24h 最高价
                "low": data.get("l", "0"),             # 24h 最低价
                "volume": data.get("v", "0"),          # 24h 成交量
                "quote_volume": data.get("q", "0"),    # 24h 成交额
                "timestamp": data.get("E", 0),         # 事件时间
            }
            
            # 写入 Redis
            r = await self._get_redis()
            key = f"{self.REDIS_KEY_PREFIX}{symbol}"
            await r.hset(key, mapping=ticker)
            await r.expire(key, 60)  # 60秒过期
            
            logger.debug(f"Saved ticker: {symbol} = {ticker['price']}")
            
        except Exception as e:
            logger.error(f"Error saving ticker: {e}")
    
    async def run(self) -> None:
        """启动爬虫"""
        self._running = True
        logger.info(f"Starting Binance Spider for {len(self.symbols)} symbols")
        logger.info(f"Stream URL: {self.stream_url}")
        
        # 获取网络管理器
        if NetworkManager:
            nm = NetworkManager()
            ws_client = nm.get_ws_client()
            logger.info(f"Using NetworkManager: {nm}")
        else:
            logger.warning("NetworkManager not available, using direct connection")
            ws_client = None
        
        while self._running:
            try:
                if ws_client:
                    # 使用统一的 WebSocket 客户端
                    async for message in ws_client.connect(self.stream_url):
                        if not self._running:
                            break
                        await self._process_message(message)
                else:
                    # 降级: 直接使用 websockets
                    import websockets
                    async with websockets.connect(self.stream_url) as ws:
                        async for message in ws:
                            if not self._running:
                                break
                            await self._process_message(message)
                            
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def _process_message(self, message: str) -> None:
        """处理 WebSocket 消息"""
        try:
            data = json.loads(message)
            
            # 处理单个 ticker 或批量 ticker
            if isinstance(data, list):
                for item in data:
                    await self._save_ticker(item)
            else:
                await self._save_ticker(data)
                
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON message: {e}")
    
    async def stop(self) -> None:
        """停止爬虫"""
        self._running = False
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("Binance Spider stopped")
