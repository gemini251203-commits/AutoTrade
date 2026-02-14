"""
Margin Service Module
=====================
保证金服务模块

提供逐仓/全仓保证金计算功能。
"""

from .calculator import MarginCalculator

__all__ = [
    "MarginCalculator",
]
