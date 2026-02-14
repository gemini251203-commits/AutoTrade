"""
Binance Client
===============
轻量级 Binance 数据获取客户端

用于获取实时行情数据，支持代理配置。
"""

from typing import Optional, Dict, Any
from loguru import logger

from app.core.network import net_manager
from app.core.circuit_breaker import CircuitBreakerInstance, CircuitBreakerError


class BinanceClient:
    """
    Binance 数据客户端
    
    提供实时行情获取功能，自动使用代理（如果配置）。
    """
    
    BASE_URL = "https://fapi.binance.com"  # 期货 API
    
    def __init__(self):
        # 断路器: 5次连续失败后断开，30s 后尝试恢复
        self._breaker = CircuitBreakerInstance(
            name="binance_api",
            failure_threshold=5,
            reset_timeout=30.0,
        )
    
    async def _request(self, method: str, url: str, timeout: float = 10.0, **kwargs) -> Any:
        """通过断路器发起 HTTP 请求"""
        async def _do_request():
            async with net_manager.get_client(timeout=timeout) as client:
                response = await client.request(method, url, **kwargs)
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
                return response.json()
        
        return await self._breaker.call(_do_request)
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取实时行情
        
        Args:
            symbol: 交易对 (例如 BTCUSDT)
        
        Returns:
            行情数据字典或 None
            
        返回字段:
            - symbol: 交易对
            - lastPrice: 最新价格
            - priceChangePercent: 24h涨跌幅
            - highPrice: 24h最高价
            - lowPrice: 24h最低价
        """
        try:
            url = f"{self.BASE_URL}/fapi/v1/ticker/24hr"
            data = await self._request("GET", url, timeout=5.0, params={"symbol": symbol.upper()})
            return {
                "symbol": data.get("symbol"),
                "lastPrice": data.get("lastPrice", "0"),
                "priceChangePercent": data.get("priceChangePercent", "0"),
                "highPrice": data.get("highPrice", "0"),
                "lowPrice": data.get("lowPrice", "0"),
                "volume": data.get("volume", "0"),
            }
        except CircuitBreakerError as e:
            logger.warning(f"[BinanceClient] {e}")
            return None
        except Exception as e:
            logger.warning(f"[BinanceClient] Error fetching ticker for {symbol}: {e}")
            return None
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """
        获取当前价格 (简化版)
        
        Args:
            symbol: 交易对
            
        Returns:
            当前价格或 None
        """
        ticker = await self.get_ticker(symbol)
        if ticker:
            try:
                return float(ticker.get("lastPrice", 0))
            except (ValueError, TypeError):
                return None
        return None
    
    async def get_klines(
        self, 
        symbol: str, 
        interval: str = "1m", 
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list:
        """
        获取 K 线历史数据
        
        Args:
            symbol: 交易对 (例如 BTCUSDT)
            interval: 时间周期 (1m, 5m, 15m, 30m, 1h, 4h, 1d)
            limit: 返回数量 (最大 1500)
            start_time: 开始时间 (毫秒时间戳)
            end_time: 结束时间 (毫秒时间戳)
        
        Returns:
            K 线数据列表，每条记录格式:
            {
                "open_time": 1234567890000,  # 毫秒
                "open": "78000.0",
                "high": "78500.0",
                "low": "77800.0",
                "close": "78200.0",
                "volume": "1234.56",
                "close_time": 1234567950000,
                "quote_volume": "96000000.0",
                "trades": 5678
            }
            
        ⚠️ 字段名使用下划线格式，与 Kline 模型一致
        """
        try:
            url = f"{self.BASE_URL}/fapi/v1/klines"
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": min(limit, 1500),
            }
            if start_time:
                params["startTime"] = start_time
            if end_time:
                params["endTime"] = end_time
            
            raw_klines = await self._request("GET", url, timeout=30.0, params=params)
            
            result = []
            for k in raw_klines:
                result.append({
                    "open_time": k[0],
                    "open": k[1],
                    "high": k[2],
                    "low": k[3],
                    "close": k[4],
                    "volume": k[5],
                    "close_time": k[6],
                    "quote_volume": k[7],
                    "trades": int(k[8]),
                })
            
            logger.debug(f"[BinanceClient] Fetched {len(result)} klines for {symbol} {interval}")
            return result
        except CircuitBreakerError as e:
            logger.warning(f"[BinanceClient] {e}")
            return []
        except Exception as e:
            logger.error(f"[BinanceClient] Error fetching klines for {symbol}: {e}")
            return []
