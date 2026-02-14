"""
Indicator Processor
====================
技术指标计算处理器
"""

import numpy as np
from typing import Dict, List, Optional
from loguru import logger


class IndicatorProcessor:
    """
    技术指标处理器
    
    支持的指标:
    - RSI (相对强弱指标)
    - MACD (移动平均收敛散度)
    - SMA (简单移动平均)
    - EMA (指数移动平均)
    - Bollinger Bands (布林带)
    """
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> Optional[float]:
        """
        计算简单移动平均线
        
        Args:
            prices: 价格列表
            period: 周期
        
        Returns:
            SMA 值或 None
        """
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> Optional[float]:
        """
        计算指数移动平均线
        
        Args:
            prices: 价格列表
            period: 周期
        
        Returns:
            EMA 值或 None
        """
        if len(prices) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """
        计算相对强弱指标 (RSI)
        
        Args:
            prices: 价格列表
            period: RSI 周期 (默认 14)
        
        Returns:
            RSI 值 (0-100) 或 None
        """
        if len(prices) < period + 1:
            return None
        
        # 计算价格变化
        deltas = np.diff(prices)
        
        # 分离上涨和下跌
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # 计算平均上涨和下跌
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return round(rsi, 2)
    
    @staticmethod
    def calculate_macd(
        prices: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Optional[Dict[str, float]]:
        """
        计算 MACD 指标
        
        Args:
            prices: 价格列表
            fast_period: 快线周期 (默认 12)
            slow_period: 慢线周期 (默认 26)
            signal_period: 信号线周期 (默认 9)
        
        Returns:
            包含 macd, signal, histogram 的字典或 None
        """
        if len(prices) < slow_period + signal_period:
            return None
        
        # 计算 EMA
        def ema_series(data: List[float], period: int) -> List[float]:
            result = []
            multiplier = 2 / (period + 1)
            ema = data[0]
            result.append(ema)
            for price in data[1:]:
                ema = (price * multiplier) + (ema * (1 - multiplier))
                result.append(ema)
            return result
        
        # 计算快慢 EMA
        fast_ema = ema_series(prices, fast_period)
        slow_ema = ema_series(prices, slow_period)
        
        # MACD 线 = 快 EMA - 慢 EMA
        macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
        
        # 信号线 = MACD 的 EMA
        signal_line = ema_series(macd_line, signal_period)
        
        # 柱状图 = MACD - 信号线
        histogram = macd_line[-1] - signal_line[-1]
        
        return {
            "macd": round(macd_line[-1], 4),
            "signal": round(signal_line[-1], 4),
            "histogram": round(histogram, 4),
        }
    
    @staticmethod
    def calculate_bollinger_bands(
        prices: List[float],
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Optional[Dict[str, float]]:
        """
        计算布林带
        
        Args:
            prices: 价格列表
            period: 周期 (默认 20)
            std_dev: 标准差倍数 (默认 2.0)
        
        Returns:
            包含 upper, middle, lower 的字典或 None
        """
        if len(prices) < period:
            return None
        
        recent_prices = prices[-period:]
        middle = sum(recent_prices) / period
        std = np.std(recent_prices)
        
        return {
            "upper": round(middle + (std * std_dev), 4),
            "middle": round(middle, 4),
            "lower": round(middle - (std * std_dev), 4),
        }
    
    def process(
        self,
        prices: List[float],
        indicators: Optional[List[str]] = None,
    ) -> Dict[str, any]:
        """
        处理价格数据，计算所有请求的指标
        
        Args:
            prices: 价格列表
            indicators: 要计算的指标列表，默认计算所有
        
        Returns:
            包含所有指标值的字典
        """
        if indicators is None:
            indicators = ["rsi", "macd", "sma_20", "ema_20", "bollinger"]
        
        result = {}
        
        if "rsi" in indicators:
            result["rsi"] = self.calculate_rsi(prices)
        
        if "macd" in indicators:
            result["macd"] = self.calculate_macd(prices)
        
        if "sma_20" in indicators:
            result["sma_20"] = self.calculate_sma(prices, 20)
        
        if "ema_20" in indicators:
            result["ema_20"] = self.calculate_ema(prices, 20)
        
        if "bollinger" in indicators:
            result["bollinger"] = self.calculate_bollinger_bands(prices)
        
        return result
