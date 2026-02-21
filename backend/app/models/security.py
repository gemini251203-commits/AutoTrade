"""
Security Spec — 品种标准化模型
==============================
LEAN 风格: 将 exchange_rules.py 的散落字典统一为 SecuritySpec 对象

数据来源:
- exchange_rules.py (静态, 来自 Binance exchangeInfo API)
- 费率: 默认 taker=0.05%, maker=0.02% (可通过配置覆盖)

用法:
    from app.models.security import security_manager

    spec = security_manager.get("ETHUSDT")
    spec.tick_size       # Decimal("0.01")
    spec.lot_size        # Decimal("0.001")
    spec.taker_fee       # Decimal("0.0005")
    spec.min_notional    # Decimal("20")
    
    # 精度工具
    security_manager.round_quantity("ETHUSDT", 1.23456789)  # 1.234
    security_manager.round_price("ETHUSDT", 3200.123456)    # 3200.12
"""

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Dict, Optional

from loguru import logger


# ============================================================
# SecuritySpec — 品种规格
# ============================================================

@dataclass(frozen=True)
class SecuritySpec:
    """
    交易品种的完整规格 (不可变)
    
    合并了 exchange_rules.py 中的 4 个字典:
    - QUANTITY_PRECISION → quantity_precision
    - STEP_SIZE → lot_size
    - TICK_SIZE → tick_size
    - MIN_NOTIONAL → min_notional
    
    以及新增的:
    - taker_fee / maker_fee (费率)
    - base_asset / quote_asset (拆分 symbol)
    """
    symbol: str                         # "ETHUSDT"
    base_asset: str                     # "ETH"
    quote_asset: str                    # "USDT"
    
    # --- 精度 ---
    quantity_precision: int             # 小数位数, e.g. 3
    price_precision: int                # 价格精度 (从 tick_size 推算)
    
    # --- 步长 ---
    lot_size: Decimal                   # 数量最小步长, e.g. 0.001
    tick_size: Decimal                  # 价格最小步长, e.g. 0.01
    
    # --- 限制 ---
    min_notional: Decimal               # 最小名义价值 (USDT)
    
    # --- 费率 ---
    taker_fee: Decimal                  # 吃单费率, e.g. 0.0005 (0.05%)
    maker_fee: Decimal                  # 挂单费率, e.g. 0.0002 (0.02%)
    
    def __repr__(self) -> str:
        return (
            f"<Security({self.symbol}, "
            f"lot={self.lot_size}, tick={self.tick_size}, "
            f"fee={self.taker_fee}/{self.maker_fee})>"
        )


# ============================================================
# 费率工具
# ============================================================

def _count_decimal_places(value_str: str) -> int:
    """从字符串推算小数位数: '0.01' → 2, '0.001' → 3"""
    if "." not in value_str:
        return 0
    decimal_part = value_str.rstrip("0").split(".")[-1]
    return len(decimal_part)


# ============================================================
# SecurityManager — 品种管理器
# ============================================================

# 默认费率 (Binance USDT-M Futures)
DEFAULT_TAKER_FEE = Decimal("0.0005")   # 0.05%
DEFAULT_MAKER_FEE = Decimal("0.0002")   # 0.02%

# 已知的 USDT/USDC 交易对的 quote asset
_QUOTE_ASSETS = ["USDT", "USDC", "BTC"]


def _split_symbol(symbol: str) -> tuple:
    """拆分交易对: ETHUSDT → (ETH, USDT)"""
    for quote in _QUOTE_ASSETS:
        if symbol.endswith(quote):
            base = symbol[: -len(quote)]
            if base:  # 避免空 base
                return base, quote
    # 无法拆分时，返回整个 symbol 作为 base
    return symbol, "UNKNOWN"


class SecurityManager:
    """
    品种管理器 (单例)
    
    初始化时从 exchange_rules.py 加载所有品种，
    提供统一的查询、精度工具。
    """
    
    def __init__(self):
        self._specs: Dict[str, SecuritySpec] = {}
        self._loaded: bool = False
    
    def _ensure_loaded(self) -> None:
        """懒加载: 首次调用时从 exchange_rules 加载"""
        if self._loaded:
            return
        
        try:
            from app.services.exchange_rules import (
                QUANTITY_PRECISION,
                STEP_SIZE,
                TICK_SIZE,
                MIN_NOTIONAL,
                DEFAULT_MIN_NOTIONAL,
            )
        except ImportError:
            logger.error("[SecurityManager] Failed to import exchange_rules")
            self._loaded = True
            return
        
        # 以 QUANTITY_PRECISION 的 keys 为主 (最完整的)
        all_symbols = set(QUANTITY_PRECISION.keys())
        
        for symbol in all_symbols:
            qty_precision = QUANTITY_PRECISION.get(symbol, 2)
            step_size_str = STEP_SIZE.get(symbol, "0.01")
            tick_size_str = TICK_SIZE.get(symbol, "0.01")
            min_notional = MIN_NOTIONAL.get(symbol, DEFAULT_MIN_NOTIONAL)
            
            # 从 tick_size 推算价格精度
            price_precision = _count_decimal_places(tick_size_str)
            
            base, quote = _split_symbol(symbol)
            
            spec = SecuritySpec(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
                quantity_precision=qty_precision,
                price_precision=price_precision,
                lot_size=Decimal(step_size_str),
                tick_size=Decimal(tick_size_str),
                min_notional=Decimal(str(min_notional)),
                taker_fee=DEFAULT_TAKER_FEE,
                maker_fee=DEFAULT_MAKER_FEE,
            )
            self._specs[symbol] = spec
        
        self._loaded = True
        logger.info(f"[SecurityManager] Loaded {len(self._specs)} securities")
    
    # --- 查询 ---
    
    def get(self, symbol: str) -> Optional[SecuritySpec]:
        """获取品种规格, 不存在返回 None"""
        self._ensure_loaded()
        return self._specs.get(symbol.upper())
    
    def get_or_default(self, symbol: str) -> SecuritySpec:
        """获取品种规格, 不存在返回默认值"""
        spec = self.get(symbol)
        if spec is not None:
            return spec
        
        # 构造默认值
        base, quote = _split_symbol(symbol.upper())
        return SecuritySpec(
            symbol=symbol.upper(),
            base_asset=base,
            quote_asset=quote,
            quantity_precision=2,
            price_precision=2,
            lot_size=Decimal("0.01"),
            tick_size=Decimal("0.01"),
            min_notional=Decimal("5"),
            taker_fee=DEFAULT_TAKER_FEE,
            maker_fee=DEFAULT_MAKER_FEE,
        )
    
    def has(self, symbol: str) -> bool:
        """检查品种是否存在"""
        self._ensure_loaded()
        return symbol.upper() in self._specs
    
    def all_symbols(self) -> list:
        """获取所有品种代码"""
        self._ensure_loaded()
        return list(self._specs.keys())
    
    def count(self) -> int:
        """品种总数"""
        self._ensure_loaded()
        return len(self._specs)
    
    # --- 精度工具 ---
    
    def round_quantity(self, symbol: str, quantity) -> Decimal:
        """按品种精度向下取整数量"""
        spec = self.get_or_default(symbol)
        qty = Decimal(str(quantity))
        factor = Decimal(10) ** spec.quantity_precision
        return (qty * factor).to_integral_value(rounding=ROUND_DOWN) / factor
    
    def round_quantity_up(self, symbol: str, quantity) -> Decimal:
        """按品种精度向上取整数量"""
        spec = self.get_or_default(symbol)
        qty = Decimal(str(quantity))
        factor = Decimal(10) ** spec.quantity_precision
        return (qty * factor).to_integral_value(rounding=ROUND_UP) / factor
    
    def round_price(self, symbol: str, price) -> Decimal:
        """按品种 tick_size 取整价格"""
        spec = self.get_or_default(symbol)
        p = Decimal(str(price))
        return (p / spec.tick_size).to_integral_value(rounding=ROUND_DOWN) * spec.tick_size
    
    def estimate_commission(
        self, symbol: str, quantity, price, is_maker: bool = False
    ) -> Decimal:
        """估算手续费"""
        spec = self.get_or_default(symbol)
        notional = Decimal(str(quantity)) * Decimal(str(price))
        fee_rate = spec.maker_fee if is_maker else spec.taker_fee
        return notional * fee_rate
    
    def validate_order(
        self, symbol: str, quantity, price, leverage: int = 1
    ) -> dict:
        """验证订单参数"""
        spec = self.get_or_default(symbol)
        qty = Decimal(str(quantity))
        p = Decimal(str(price))
        notional = qty * p
        
        if notional < spec.min_notional:
            min_qty = self.round_quantity_up(symbol, spec.min_notional / p)
            suggested_margin = (min_qty * p) / leverage if leverage > 0 else min_qty * p
            return {
                "valid": False,
                "error": (
                    f"名义价值不足: {qty} × ${p:,.2f} = ${notional:,.2f}, "
                    f"但 {symbol} 最小名义为 ${spec.min_notional}。\n"
                    f"建议: quantity={min_qty} (名义=${min_qty * p:,.2f}), "
                    f"保证金约 ${suggested_margin:,.2f} ({leverage}x杠杆)"
                ),
                "suggestion": {
                    "symbol": symbol,
                    "min_quantity": min_qty,
                    "min_notional": spec.min_notional,
                    "suggested_margin": suggested_margin.quantize(Decimal("0.01")),
                    "current_price": p,
                },
            }
        
        return {"valid": True, "error": None, "suggestion": None}
    
    # --- 费率配置 ---
    
    def set_fee_override(
        self,
        symbol: str,
        taker_fee: Optional[Decimal] = None,
        maker_fee: Optional[Decimal] = None,
    ) -> None:
        """覆盖特定品种的费率 (例如 VIP 费率、BNB 抵扣)"""
        self._ensure_loaded()
        old_spec = self._specs.get(symbol.upper())
        if old_spec is None:
            return
        
        # frozen dataclass, 需要重建
        new_spec = SecuritySpec(
            symbol=old_spec.symbol,
            base_asset=old_spec.base_asset,
            quote_asset=old_spec.quote_asset,
            quantity_precision=old_spec.quantity_precision,
            price_precision=old_spec.price_precision,
            lot_size=old_spec.lot_size,
            tick_size=old_spec.tick_size,
            min_notional=old_spec.min_notional,
            taker_fee=taker_fee if taker_fee is not None else old_spec.taker_fee,
            maker_fee=maker_fee if maker_fee is not None else old_spec.maker_fee,
        )
        self._specs[symbol.upper()] = new_spec
    
    def set_global_fee(
        self, taker_fee: Decimal, maker_fee: Decimal
    ) -> None:
        """设置全局费率 (例如 VIP 等级变更, 会重新加载所有品种)"""
        global DEFAULT_TAKER_FEE, DEFAULT_MAKER_FEE
        DEFAULT_TAKER_FEE = taker_fee
        DEFAULT_MAKER_FEE = maker_fee
        self._loaded = False  # 触发重新加载
        logger.info(
            f"[SecurityManager] Global fee updated: "
            f"taker={taker_fee}, maker={maker_fee}"
        )


# ============================================================
# 全局单例
# ============================================================

security_manager = SecurityManager()
