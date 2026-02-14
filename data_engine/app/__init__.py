"""
AutoTrade Data Engine
======================
独立爬虫服务 - 系统的"眼睛"

职责:
- 连接 Binance/OKX WebSocket
- 清洗数据
- 计算指标 (RSI/MACD)
- 写入 Redis

原则: 只负责看和算，不负责交易
"""

from .spiders import BinanceSpider, OKXSpider
from .processors import IndicatorProcessor

__all__ = ["BinanceSpider", "OKXSpider", "IndicatorProcessor"]
