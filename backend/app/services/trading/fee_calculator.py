"""
Fee Calculator — 币安 USDⓈ-M 合约费率 & 滑点计算
=====================================================

费率参数 (VIP0 基础费率):
- Taker (市价/主动吃单): 0.05%
- Maker (限价/挂单成交):  0.02%

滑点模型:
- 市价单: 按百分比模拟 bid-ask spread
  - 买入: price × (1 + slippage)
  - 卖出: price × (1 - slippage)
- 限价单: 无滑点 (精确价格成交)

开仓成本公式 (币安官方):
  Cost = Initial Margin + Commission
  Initial Margin = Notional / Leverage
  Commission = Notional × Fee Rate
  Notional = Quantity × Price
"""

from decimal import Decimal, ROUND_DOWN
from loguru import logger


# ============================================
# 币安 USDⓈ-M 合约基础费率 (VIP0)
# ============================================
TAKER_FEE_RATE = Decimal("0.0005")      # 0.05% — 市价单
MAKER_FEE_RATE = Decimal("0.0002")      # 0.02% — 限价单
LIQUIDATION_FEE_RATE = Decimal("0.00015")  # 0.015% — 强平清算费

# ============================================
# 滑点参数
# ============================================
DEFAULT_SLIPPAGE_RATE = Decimal("0.0005")   # 0.05% — 市价单默认滑点


class FeeCalculator:
    """
    费率计算器

    集中处理所有交易费用相关计算:
    - 手续费
    - 滑点
    - 开仓成本
    """
    
    # 类级别常量 (方便外部引用 FeeCalculator.XXX)
    TAKER_FEE_RATE = TAKER_FEE_RATE
    MAKER_FEE_RATE = MAKER_FEE_RATE
    LIQUIDATION_FEE_RATE = LIQUIDATION_FEE_RATE

    @staticmethod
    def get_fee_rate(is_maker: bool = False) -> Decimal:
        """
        获取手续费率

        Args:
            is_maker: 是否为 Maker 单 (限价单挂单成交)

        Returns:
            费率 Decimal
        """
        return MAKER_FEE_RATE if is_maker else TAKER_FEE_RATE

    @staticmethod
    def calculate_commission(
        quantity: Decimal,
        price: Decimal,
        is_maker: bool = False,
    ) -> Decimal:
        """
        计算手续费

        公式: Commission = Notional × Fee Rate
              Notional = Quantity × Price

        Args:
            quantity: 交易数量
            price: 成交价格
            is_maker: 是否为 Maker 单

        Returns:
            手续费金额 (USDT)
        """
        notional = quantity * price
        fee_rate = FeeCalculator.get_fee_rate(is_maker)
        commission = notional * fee_rate
        # 保留 8 位小数, 向下取整 (不多扣)
        return commission.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    @staticmethod
    def apply_slippage(
        price: Decimal,
        side: str,
        slippage_rate: Decimal = DEFAULT_SLIPPAGE_RATE,
    ) -> Decimal:
        """
        市价单滑点模拟

        买入: price × (1 + slippage) → 成交价偏高
        卖出: price × (1 - slippage) → 成交价偏低

        Args:
            price: 标记价格
            side: "buy" 或 "sell"
            slippage_rate: 滑点率 (默认 0.05%)

        Returns:
            应用滑点后的成交价格
        """
        if side == "buy":
            slipped = price * (Decimal("1") + slippage_rate)
        else:
            slipped = price * (Decimal("1") - slippage_rate)

        logger.debug(
            f"[FeeCalculator] Slippage: {price} → {slipped} "
            f"({side}, rate={slippage_rate})"
        )
        return slipped

    @staticmethod
    def calculate_open_cost(
        quantity: Decimal,
        price: Decimal,
        leverage: int,
        is_maker: bool = False,
    ) -> tuple[Decimal, Decimal]:
        """
        计算开仓总成本

        Cost = Initial Margin + Commission

        Args:
            quantity: 开仓数量
            price: 开仓价格
            leverage: 杠杆倍数
            is_maker: 是否为 Maker 单

        Returns:
            (initial_margin, commission) 元组
        """
        notional = quantity * price
        initial_margin = notional / Decimal(leverage)
        commission = FeeCalculator.calculate_commission(quantity, price, is_maker)

        logger.info(
            f"[FeeCalculator] Open cost: notional={notional}, "
            f"margin={initial_margin}, commission={commission}, "
            f"total={initial_margin + commission}"
        )
        return initial_margin, commission
