"""
Data Engine Spiders
===================
交易所数据爬虫模块
"""

from .binance_spider import BinanceSpider

# OKX Spider 待实现
class OKXSpider:
    """OKX 爬虫 (占位)"""
    pass

__all__ = ["BinanceSpider", "OKXSpider"]
