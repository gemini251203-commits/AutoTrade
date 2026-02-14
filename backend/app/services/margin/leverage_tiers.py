"""
Binance Leverage Tiers Configuration
=====================================
真实币安合约杠杆档位配置

数据来源: Binance USDT-M Futures (2024.05.28 更新)

功能:
1. 根据仓位名义价值获取最大杠杆
2. 根据档位获取维持保证金率
3. 验证杠杆是否符合规则
"""

from decimal import Decimal
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class LeverageTier:
    """杠杆档位"""
    min_notional: Decimal      # 最小名义价值 (USDT)
    max_notional: Decimal      # 最大名义价值 (USDT)
    max_leverage: int          # 最大杠杆
    maintenance_margin_rate: Decimal  # 维持保证金率


# ============================================
# 币安 BTCUSDT 杠杆档位 (2024.05.28)
# ============================================

BTCUSDT_TIERS: List[LeverageTier] = [
    LeverageTier(Decimal("0"), Decimal("50000"), 125, Decimal("0.004")),
    LeverageTier(Decimal("50000"), Decimal("600000"), 100, Decimal("0.005")),
    LeverageTier(Decimal("600000"), Decimal("3000000"), 75, Decimal("0.0065")),
    LeverageTier(Decimal("3000000"), Decimal("12000000"), 50, Decimal("0.01")),
    LeverageTier(Decimal("12000000"), Decimal("70000000"), 25, Decimal("0.02")),
    LeverageTier(Decimal("70000000"), Decimal("100000000"), 20, Decimal("0.025")),
    LeverageTier(Decimal("100000000"), Decimal("230000000"), 10, Decimal("0.05")),
    LeverageTier(Decimal("230000000"), Decimal("480000000"), 5, Decimal("0.10")),
    LeverageTier(Decimal("480000000"), Decimal("600000000"), 4, Decimal("0.125")),
    LeverageTier(Decimal("600000000"), Decimal("800000000"), 3, Decimal("0.15")),
    LeverageTier(Decimal("800000000"), Decimal("1200000000"), 2, Decimal("0.25")),
    LeverageTier(Decimal("1200000000"), Decimal("999999999999"), 1, Decimal("0.50")),
]


# ============================================
# ETHUSDT 杠杆档位 (A 类)
# ============================================

ETHUSDT_TIERS: List[LeverageTier] = [
    LeverageTier(Decimal("0"), Decimal("25000"), 100, Decimal("0.005")),
    LeverageTier(Decimal("25000"), Decimal("200000"), 75, Decimal("0.0065")),
    LeverageTier(Decimal("200000"), Decimal("1000000"), 50, Decimal("0.01")),
    LeverageTier(Decimal("1000000"), Decimal("5000000"), 25, Decimal("0.02")),
    LeverageTier(Decimal("5000000"), Decimal("20000000"), 20, Decimal("0.025")),
    LeverageTier(Decimal("20000000"), Decimal("50000000"), 10, Decimal("0.05")),
    LeverageTier(Decimal("50000000"), Decimal("100000000"), 5, Decimal("0.10")),
    LeverageTier(Decimal("100000000"), Decimal("999999999999"), 2, Decimal("0.25")),
]


# ============================================
# B 类币种 (BNB, SOL, XRP, LTC, DOGE)
# ============================================

CLASS_B_TIERS: List[LeverageTier] = [
    LeverageTier(Decimal("0"), Decimal("10000"), 75, Decimal("0.0065")),
    LeverageTier(Decimal("10000"), Decimal("100000"), 50, Decimal("0.01")),
    LeverageTier(Decimal("100000"), Decimal("500000"), 25, Decimal("0.02")),
    LeverageTier(Decimal("500000"), Decimal("2000000"), 20, Decimal("0.025")),
    LeverageTier(Decimal("2000000"), Decimal("10000000"), 10, Decimal("0.05")),
    LeverageTier(Decimal("10000000"), Decimal("999999999999"), 5, Decimal("0.10")),
]


# ============================================
# C 类币种 (ASTER, XAU - 新币/商品，低杠杆)
# ============================================

CLASS_C_TIERS: List[LeverageTier] = [
    LeverageTier(Decimal("0"), Decimal("5000"), 20, Decimal("0.025")),
    LeverageTier(Decimal("5000"), Decimal("50000"), 10, Decimal("0.05")),
    LeverageTier(Decimal("50000"), Decimal("200000"), 5, Decimal("0.10")),
    LeverageTier(Decimal("200000"), Decimal("999999999999"), 2, Decimal("0.25")),
]


# ============================================
# 币种到档位表的映射
# ============================================

SYMBOL_TIERS = {
    # A 类
    "BTCUSDT": BTCUSDT_TIERS,
    "ETHUSDT": ETHUSDT_TIERS,
    
    # B 类
    "BNBUSDT": CLASS_B_TIERS,
    "SOLUSDT": CLASS_B_TIERS,
    "XRPUSDT": CLASS_B_TIERS,
    "LTCUSDT": CLASS_B_TIERS,
    "DOGEUSDT": CLASS_B_TIERS,
    
    # C 类 (新币/商品)
    "ASTERUSDT": CLASS_C_TIERS,
    "XAUUSDT": CLASS_C_TIERS,
}

# 默认档位 (未配置的币种)
DEFAULT_TIERS = CLASS_B_TIERS


# ============================================
# 全局配置
# ============================================

# 最小名义价值 (USDT)
MIN_NOTIONAL_VALUE = Decimal("5")


# ============================================
# 工具函数
# ============================================

def get_tiers(symbol: str) -> List[LeverageTier]:
    """获取币种的杠杆档位表"""
    return SYMBOL_TIERS.get(symbol.upper(), DEFAULT_TIERS)


def get_tier_for_notional(symbol: str, notional: Decimal) -> LeverageTier:
    """
    根据名义价值获取对应的档位
    
    Args:
        symbol: 交易对 (如 BTCUSDT)
        notional: 名义价值 (USDT)
        
    Returns:
        LeverageTier: 对应的档位配置
    """
    tiers = get_tiers(symbol)
    
    for tier in tiers:
        if tier.min_notional <= notional < tier.max_notional:
            return tier
    
    # 返回最高档位
    return tiers[-1]


def get_max_leverage(symbol: str, notional: Decimal) -> int:
    """
    获取指定仓位的最大允许杠杆
    
    Args:
        symbol: 交易对
        notional: 名义价值 (USDT)
        
    Returns:
        int: 最大杠杆倍数
    """
    tier = get_tier_for_notional(symbol, notional)
    return tier.max_leverage


def get_maintenance_margin_rate(symbol: str, notional: Decimal) -> Decimal:
    """
    获取维持保证金率
    
    Args:
        symbol: 交易对
        notional: 名义价值 (USDT)
        
    Returns:
        Decimal: 维持保证金率 (如 0.004 表示 0.4%)
    """
    tier = get_tier_for_notional(symbol, notional)
    return tier.maintenance_margin_rate


def validate_leverage(
    symbol: str,
    notional: Decimal,
    leverage: int
) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    验证杠杆是否符合规则
    
    Args:
        symbol: 交易对
        notional: 名义价值 (USDT)
        leverage: 请求的杠杆
        
    Returns:
        Tuple[bool, str, int]: (是否合规, 错误信息, 最大允许杠杆)
    """
    # 检查最小名义价值
    if notional < MIN_NOTIONAL_VALUE:
        return False, f"名义价值必须 ≥ {MIN_NOTIONAL_VALUE} USDT", None
    
    # 检查杠杆 ≥ 1
    if leverage < 1:
        return False, "杠杆必须 ≥ 1", None
    
    # 获取最大杠杆
    max_lev = get_max_leverage(symbol, notional)
    
    if leverage > max_lev:
        return False, f"仓位 {notional:.0f} USDT 最大杠杆为 {max_lev}x", max_lev
    
    return True, None, max_lev


def calculate_max_position_for_leverage(
    symbol: str,
    leverage: int
) -> Optional[Decimal]:
    """
    计算指定杠杆下的最大仓位
    
    Args:
        symbol: 交易对
        leverage: 杠杆倍数
        
    Returns:
        Decimal: 最大名义价值，如果杠杆不可用则返回 None
    """
    tiers = get_tiers(symbol)
    
    for tier in tiers:
        if tier.max_leverage >= leverage:
            return tier.max_notional
    
    return None


def get_symbol_max_leverage(symbol: str) -> int:
    """获取币种的最大可用杠杆"""
    tiers = get_tiers(symbol)
    return tiers[0].max_leverage if tiers else 1
