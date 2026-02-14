"""
Business Services
==================
核心业务逻辑服务 - 模块化版本

子模块:
- wallet: 钱包管理
- trading: 交易执行 (仓位/订单)
- exchange: 交易所适配器 (模拟盘/真实交易所)
- risk: 风控引擎
- grid: 网格交易
"""

# 从子模块导出常用类，保持向后兼容
from .wallet import WalletManager, InsufficientFundsError
from .strategy_engine import StrategyEngine

__all__ = [
    # Wallet
    "WalletManager",
    "InsufficientFundsError",
    # Strategy
    "StrategyEngine",
]
