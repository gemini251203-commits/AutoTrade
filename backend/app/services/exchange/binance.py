"""
Binance Client
===============
轻量级 Binance 数据获取客户端

用于获取实时行情数据，支持代理配置。
"""

from typing import Optional, Dict, Any
from loguru import logger

from app.core.network import net_manager


class BinanceClient:
    """
    Binance 数据客户端
    
    提供实时行情获取功能，自动使用代理（如果配置）。
    """
    
    BASE_URL = "https://fapi.binance.com"  # 期货 API
    
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
            async with net_manager.get_client(timeout=5.0) as client:
                url = f"{self.BASE_URL}/fapi/v1/ticker/24hr"
                response = await client.get(url, params={"symbol": symbol.upper()})
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "symbol": data.get("symbol"),
                        "lastPrice": data.get("lastPrice", "0"),
                        "priceChangePercent": data.get("priceChangePercent", "0"),
                        "highPrice": data.get("highPrice", "0"),
                        "lowPrice": data.get("lowPrice", "0"),
                        "volume": data.get("volume", "0"),
                    }
                else:
                    logger.warning(f"[BinanceClient] Failed to get ticker: {response.status_code}")
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
            async with net_manager.get_client(timeout=30.0) as client:
                url = f"{self.BASE_URL}/fapi/v1/klines"
                params = {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "limit": min(limit, 1500),  # 币安最大 1500
                }
                if start_time:
                    params["startTime"] = start_time
                if end_time:
                    params["endTime"] = end_time
                
                response = await client.get(url, params=params)
                
                if response.status_code == 200:
                    raw_klines = response.json()
                    
                    # 转换为标准格式 (币安返回数组格式)
                    # [open_time, open, high, low, close, volume, close_time, 
                    #  quote_volume, trades, taker_buy_volume, taker_buy_quote_volume, ignore]
                    result = []
                    for k in raw_klines:
                        result.append({
                            "open_time": k[0],           # 开盘时间 (毫秒)
                            "open": k[1],                # 开盘价
                            "high": k[2],                # 最高价
                            "low": k[3],                 # 最低价
                            "close": k[4],               # 收盘价
                            "volume": k[5],              # 成交量
                            "close_time": k[6],          # 收盘时间
                            "quote_volume": k[7],        # 成交额
                            "trades": int(k[8]),         # 成交笔数
                        })
                    
                    logger.debug(f"[BinanceClient] Fetched {len(result)} klines for {symbol} {interval}")
                    return result
                else:
                    logger.warning(f"[BinanceClient] Failed to get klines: {response.status_code} - {response.text}")
                    return []
                    
        except Exception as e:
            logger.error(f"[BinanceClient] Error fetching klines for {symbol}: {e}")
            return []
