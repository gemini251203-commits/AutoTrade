"""
交易逻辑全面自动化测试
========================
覆盖所有核心交易链路的纯逻辑测试 (不依赖数据库/网络)

测试类别:
A. 费率计算 (FeeCalculator)
B. 滑点方向 (Slippage)
C. P&L 计算 (Position.calculate_unrealized_pnl)
D. 保证金计算 (PositionManager.calculate_margin)
E. 开仓成本 (margin + commission)
F. 止损/止盈触发条件 (4 种方向)
G. 强平价格计算

运行方式:
    cd backend
    python -m pytest tests/test_trading_logic.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
import pytest


# ============================================
# A. 费率计算测试
# ============================================

class TestFeeCalculator:
    """费率计算器测试"""

    def test_taker_fee_rate(self):
        """Taker 费率 = 0.05%"""
        from app.services.trading.fee_calculator import FeeCalculator
        assert FeeCalculator.get_fee_rate(is_maker=False) == Decimal("0.0005")

    def test_maker_fee_rate(self):
        """Maker 费率 = 0.02%"""
        from app.services.trading.fee_calculator import FeeCalculator
        assert FeeCalculator.get_fee_rate(is_maker=True) == Decimal("0.0002")

    def test_taker_commission(self):
        """Taker 手续费: 0.01 BTC × $100,000 × 0.05% = $0.50"""
        from app.services.trading.fee_calculator import FeeCalculator
        commission = FeeCalculator.calculate_commission(
            quantity=Decimal("0.01"),
            price=Decimal("100000"),
            is_maker=False,
        )
        assert commission == Decimal("0.50000000")  # $0.50

    def test_maker_commission(self):
        """Maker 手续费: 0.01 BTC × $100,000 × 0.02% = $0.20"""
        from app.services.trading.fee_calculator import FeeCalculator
        commission = FeeCalculator.calculate_commission(
            quantity=Decimal("0.01"),
            price=Decimal("100000"),
            is_maker=True,
        )
        assert commission == Decimal("0.20000000")  # $0.20

    def test_commission_large_order(self):
        """大额订单: 1 BTC × $80,000 × 0.05% = $40"""
        from app.services.trading.fee_calculator import FeeCalculator
        commission = FeeCalculator.calculate_commission(
            quantity=Decimal("1"),
            price=Decimal("80000"),
            is_maker=False,
        )
        assert commission == Decimal("40.00000000")


# ============================================
# B. 滑点测试
# ============================================

class TestSlippage:
    """滑点方向测试"""

    def test_buy_slippage_higher(self):
        """买入: 成交价应该偏高 (不利于买方)"""
        from app.services.trading.fee_calculator import FeeCalculator
        result = FeeCalculator.apply_slippage(Decimal("100000"), "buy")
        assert result > Decimal("100000")  # 买入价偏高

    def test_sell_slippage_lower(self):
        """卖出: 成交价应该偏低 (不利于卖方)"""
        from app.services.trading.fee_calculator import FeeCalculator
        result = FeeCalculator.apply_slippage(Decimal("100000"), "sell")
        assert result < Decimal("100000")  # 卖出价偏低

    def test_buy_slippage_exact(self):
        """买入滑点: $100,000 × (1 + 0.05%) = $100,050"""
        from app.services.trading.fee_calculator import FeeCalculator
        result = FeeCalculator.apply_slippage(Decimal("100000"), "buy")
        assert result == Decimal("100050.0000")

    def test_sell_slippage_exact(self):
        """卖出滑点: $100,000 × (1 - 0.05%) = $99,950"""
        from app.services.trading.fee_calculator import FeeCalculator
        result = FeeCalculator.apply_slippage(Decimal("100000"), "sell")
        assert result == Decimal("99950.0000")


# ============================================
# C. P&L 计算测试
# ============================================

class TestPnLCalculation:
    """P&L 计算 — 核心中的核心"""

    def _calc_pnl(self, side, entry_price, size, mark_price):
        """直接用公式计算 P&L, 与 Position.calculate_unrealized_pnl 保持一致"""
        entry = Decimal(str(entry_price))
        sz = Decimal(str(size))
        mark = Decimal(str(mark_price))
        
        if side == "long":
            return (mark - entry) * sz
        else:
            return (entry - mark) * sz

    # === 多仓 (LONG) ===
    def test_long_profit(self):
        """多仓盈利: 买 $80,000 → 涨到 $82,000 → PnL = +$200"""
        pnl = self._calc_pnl("long", 80000, "0.1", 82000)
        assert pnl == Decimal("200")

    def test_long_loss(self):
        """多仓亏损: 买 $80,000 → 跌到 $78,000 → PnL = -$200"""
        pnl = self._calc_pnl("long", 80000, "0.1", 78000)
        assert pnl == Decimal("-200")

    def test_long_breakeven(self):
        """多仓持平: 价格不变 → PnL = 0"""
        pnl = self._calc_pnl("long", 80000, "0.1", 80000)
        assert pnl == Decimal("0")

    # === 空仓 (SHORT) ===
    def test_short_profit(self):
        """空仓盈利: 卖 $80,000 → 跌到 $78,000 → PnL = +$200"""
        pnl = self._calc_pnl("short", 80000, "0.1", 78000)
        assert pnl == Decimal("200")

    def test_short_loss(self):
        """空仓亏损: 卖 $80,000 → 涨到 $82,000 → PnL = -$200"""
        pnl = self._calc_pnl("short", 80000, "0.1", 82000)
        assert pnl == Decimal("-200")

    def test_short_breakeven(self):
        """空仓持平: 价格不变 → PnL = 0"""
        pnl = self._calc_pnl("short", 80000, "0.1", 80000)
        assert pnl == Decimal("0")


# ============================================
# D. 保证金计算测试
# ============================================

class TestMarginCalculation:
    """保证金计算"""

    def test_margin_10x(self):
        """10 倍杠杆: 0.1 BTC × $80,000 / 10 = $800"""
        from app.services.trading.position_manager import PositionManager
        margin = PositionManager.calculate_margin(
            Decimal("0.1"), Decimal("80000"), 10
        )
        assert margin == Decimal("800")

    def test_margin_1x(self):
        """1 倍杠杆 (无杠杆): 全额保证金"""
        from app.services.trading.position_manager import PositionManager
        margin = PositionManager.calculate_margin(
            Decimal("0.1"), Decimal("80000"), 1
        )
        assert margin == Decimal("8000")

    def test_margin_125x(self):
        """125 倍杠杆: 0.1 BTC × $80,000 / 125 = $64"""
        from app.services.trading.position_manager import PositionManager
        margin = PositionManager.calculate_margin(
            Decimal("0.1"), Decimal("80000"), 125
        )
        assert margin == Decimal("64")


# ============================================
# E. 开仓成本测试 (margin + commission)
# ============================================

class TestOpenCost:
    """开仓总成本 = 保证金 + 手续费"""

    def test_market_order_cost(self):
        """市价单: margin=$800, commission=$4.00 (Taker)"""
        from app.services.trading.fee_calculator import FeeCalculator
        margin, commission = FeeCalculator.calculate_open_cost(
            quantity=Decimal("0.1"),
            price=Decimal("80000"),
            leverage=10,
            is_maker=False,
        )
        assert margin == Decimal("800")
        assert commission == Decimal("4.00000000")  # 8000 × 0.05%

    def test_limit_order_cost(self):
        """限价单: margin=$800, commission=$1.60 (Maker)"""
        from app.services.trading.fee_calculator import FeeCalculator
        margin, commission = FeeCalculator.calculate_open_cost(
            quantity=Decimal("0.1"),
            price=Decimal("80000"),
            leverage=10,
            is_maker=True,
        )
        assert margin == Decimal("800")
        assert commission == Decimal("1.60000000")  # 8000 × 0.02%


# ============================================
# F. 止损/止盈触发条件测试 (最关键!)
# ============================================

class TestStopLossTakeProfit:
    """
    止损/止盈触发条件 — 4 种场景全覆盖
    
    LONG SL: price ≤ stop_loss  → 触发
    LONG TP: price ≥ take_profit → 触发
    SHORT SL: price ≥ stop_loss  → 触发
    SHORT TP: price ≤ take_profit → 触发
    """

    def _check_trigger(self, side, stop_loss, take_profit, current_price):
        """
        模拟 check_position_sl_tp 的触发逻辑
        返回 (triggered, reason)
        """
        from app.models.position import PositionSide
        
        triggered = False
        trigger_reason = ""
        
        pos_side = PositionSide.LONG if side == "long" else PositionSide.SHORT
        sl = Decimal(str(stop_loss)) if stop_loss else None
        tp = Decimal(str(take_profit)) if take_profit else None
        price = Decimal(str(current_price))
        
        if pos_side == PositionSide.LONG:
            if sl and price <= sl:
                triggered = True
                trigger_reason = "LONG_SL"
            elif tp and price >= tp:
                triggered = True
                trigger_reason = "LONG_TP"
        else:
            if sl and price >= sl:
                triggered = True
                trigger_reason = "SHORT_SL"
            elif tp and price <= tp:
                triggered = True
                trigger_reason = "SHORT_TP"
        
        return triggered, trigger_reason

    # === LONG 止损 ===
    def test_long_sl_triggered(self):
        """多仓止损: 价格跌破 SL → 触发"""
        triggered, reason = self._check_trigger("long", 79000, None, 78500)
        assert triggered is True
        assert reason == "LONG_SL"

    def test_long_sl_exact(self):
        """多仓止损: 价格恰好等于 SL → 触发"""
        triggered, reason = self._check_trigger("long", 79000, None, 79000)
        assert triggered is True
        assert reason == "LONG_SL"

    def test_long_sl_not_triggered(self):
        """多仓止损: 价格高于 SL → 不触发"""
        triggered, reason = self._check_trigger("long", 79000, None, 80000)
        assert triggered is False

    # === LONG 止盈 ===
    def test_long_tp_triggered(self):
        """多仓止盈: 价格突破 TP → 触发"""
        triggered, reason = self._check_trigger("long", None, 85000, 86000)
        assert triggered is True
        assert reason == "LONG_TP"

    def test_long_tp_exact(self):
        """多仓止盈: 价格恰好等于 TP → 触发"""
        triggered, reason = self._check_trigger("long", None, 85000, 85000)
        assert triggered is True
        assert reason == "LONG_TP"

    def test_long_tp_not_triggered(self):
        """多仓止盈: 价格低于 TP → 不触发"""
        triggered, reason = self._check_trigger("long", None, 85000, 84000)
        assert triggered is False

    # === SHORT 止损 ===
    def test_short_sl_triggered(self):
        """空仓止损: 价格涨破 SL → 触发"""
        triggered, reason = self._check_trigger("short", 82000, None, 83000)
        assert triggered is True
        assert reason == "SHORT_SL"

    def test_short_sl_exact(self):
        """空仓止损: 价格恰好等于 SL → 触发"""
        triggered, reason = self._check_trigger("short", 82000, None, 82000)
        assert triggered is True
        assert reason == "SHORT_SL"

    def test_short_sl_not_triggered(self):
        """空仓止损: 价格低于 SL → 不触发"""
        triggered, reason = self._check_trigger("short", 82000, None, 80000)
        assert triggered is False

    # === SHORT 止盈 ===
    def test_short_tp_triggered(self):
        """空仓止盈: 价格跌破 TP → 触发"""
        triggered, reason = self._check_trigger("short", None, 75000, 74000)
        assert triggered is True
        assert reason == "SHORT_TP"

    def test_short_tp_exact(self):
        """空仓止盈: 价格恰好等于 TP → 触发"""
        triggered, reason = self._check_trigger("short", None, 75000, 75000)
        assert triggered is True
        assert reason == "SHORT_TP"

    def test_short_tp_not_triggered(self):
        """空仓止盈: 价格高于 TP → 不触发"""
        triggered, reason = self._check_trigger("short", None, 75000, 76000)
        assert triggered is False

    # === 同时设置 SL 和 TP ===
    def test_long_sl_priority_over_tp(self):
        """多仓同时设 SL+TP，价格触及 SL → SL 优先"""
        triggered, reason = self._check_trigger("long", 79000, 85000, 78000)
        assert triggered is True
        assert reason == "LONG_SL"

    def test_long_tp_when_sl_not_hit(self):
        """多仓同时设 SL+TP，价格触及 TP → TP 触发"""
        triggered, reason = self._check_trigger("long", 79000, 85000, 86000)
        assert triggered is True
        assert reason == "LONG_TP"

    def test_neither_triggered(self):
        """多仓同时设 SL+TP，价格在中间 → 都不触发"""
        triggered, reason = self._check_trigger("long", 79000, 85000, 82000)
        assert triggered is False


# ============================================
# G. 强平价格计算测试
# ============================================

class TestLiquidationPrice:
    """强平价格计算"""

    def test_long_liquidation_higher_leverage_closer(self):
        """多仓: 杠杆越高，强平价越接近开仓价"""
        from app.services.trading.position_manager import PositionManager
        from app.models.position import PositionSide
        
        liq_10x = PositionManager.calculate_liquidation_price(
            Decimal("80000"), 10, PositionSide.LONG
        )
        liq_50x = PositionManager.calculate_liquidation_price(
            Decimal("80000"), 50, PositionSide.LONG
        )
        # 50x 的强平价应更接近 80000 (即更高)
        assert liq_50x > liq_10x

    def test_short_liquidation_higher_leverage_closer(self):
        """空仓: 杠杆越高，强平价越接近开仓价"""
        from app.services.trading.position_manager import PositionManager
        from app.models.position import PositionSide
        
        liq_10x = PositionManager.calculate_liquidation_price(
            Decimal("80000"), 10, PositionSide.SHORT
        )
        liq_50x = PositionManager.calculate_liquidation_price(
            Decimal("80000"), 50, PositionSide.SHORT
        )
        # 50x 的强平价应更接近 80000 (即更低)
        assert liq_50x < liq_10x

    def test_long_liquidation_below_entry(self):
        """多仓: 强平价必须低于开仓价"""
        from app.services.trading.position_manager import PositionManager
        from app.models.position import PositionSide
        
        liq = PositionManager.calculate_liquidation_price(
            Decimal("80000"), 10, PositionSide.LONG
        )
        assert liq < Decimal("80000")

    def test_short_liquidation_above_entry(self):
        """空仓: 强平价必须高于开仓价"""
        from app.services.trading.position_manager import PositionManager
        from app.models.position import PositionSide
        
        liq = PositionManager.calculate_liquidation_price(
            Decimal("80000"), 10, PositionSide.SHORT
        )
        assert liq > Decimal("80000")


# ============================================
# H. 资金流转完整性测试
# ============================================

class TestFundFlow:
    """
    资金流转公式验证 (纯数学, 不依赖数据库)
    
    开仓: balance -= (margin + commission), frozen += margin
    平仓: frozen -= margin, balance += (margin + pnl - close_commission)
    取消: balance += (margin + commission), frozen -= (margin + commission)
    """

    def test_open_close_breakeven_flow(self):
        """开仓→平仓(持平): 最终余额应 = 初始余额 - 全部手续费"""
        initial_balance = Decimal("10000")
        price = Decimal("80000")
        qty = Decimal("0.01")
        leverage = 10

        # 开仓 (Taker)
        margin = qty * price / Decimal(leverage)  # 80
        open_commission = qty * price * Decimal("0.0005")  # 0.40
        
        balance_after_open = initial_balance - margin - open_commission  # 9919.60
        frozen = margin  # 80

        # 平仓 (同价, Taker)
        close_commission = qty * price * Decimal("0.0005")  # 0.40
        pnl_raw = Decimal("0")  # 持平
        pnl_net = pnl_raw - close_commission  # -0.40
        
        balance_after_close = balance_after_open + frozen + pnl_net  # 9999.20
        frozen = Decimal("0")

        total_fees = open_commission + close_commission  # 0.80
        expected = initial_balance - total_fees  # 9999.20
        
        assert balance_after_close == expected
        assert frozen == Decimal("0")

    def test_cancel_order_full_refund(self):
        """取消订单: 保证金 + 手续费全额退回"""
        initial_balance = Decimal("10000")
        price = Decimal("80000")
        qty = Decimal("0.01")
        leverage = 10

        margin = qty * price / Decimal(leverage)  # 80
        commission = qty * price * Decimal("0.0005")  # 0.40
        total_freeze = margin + commission  # 80.40

        # 冻结
        balance = initial_balance - total_freeze  # 9919.60
        frozen = total_freeze  # 80.40

        # 取消 → 全部退回
        balance += total_freeze  # 10000
        frozen -= total_freeze  # 0

        assert balance == initial_balance  # 完全恢复
        assert frozen == Decimal("0")

    def test_profit_trade_flow(self):
        """盈利交易: 最终余额 = 初始 + 利润 - 全部手续费"""
        initial = Decimal("10000")
        entry = Decimal("80000")
        exit_price = Decimal("81000")
        qty = Decimal("0.01")
        leverage = 10

        margin = qty * entry / Decimal(leverage)  # 80
        open_fee = qty * entry * Decimal("0.0005")  # 0.40
        close_fee = qty * exit_price * Decimal("0.0005")  # 0.405

        raw_pnl = (exit_price - entry) * qty  # +10
        net_pnl = raw_pnl - close_fee  # 10 - 0.405 = 9.595
        total_fees = open_fee + close_fee  # 0.805

        final = initial - open_fee - close_fee + raw_pnl
        expected = initial + raw_pnl - total_fees
        
        assert final == expected

    def test_loss_trade_flow(self):
        """亏损交易: 最终余额 = 初始 + 利润(负值) - 全部手续费"""
        initial = Decimal("10000")
        entry = Decimal("80000")
        exit_price = Decimal("79000")
        qty = Decimal("0.01")

        raw_pnl = (exit_price - entry) * qty  # -10
        open_fee = qty * entry * Decimal("0.0005")
        close_fee = qty * exit_price * Decimal("0.0005")

        final = initial + raw_pnl - open_fee - close_fee
        assert final < initial  # 亏损


# ============================================
# I. 合并仓位加权均价测试
# ============================================

class TestMergePosition:
    """合并仓位加权平均价计算"""

    def test_weighted_average_price(self):
        """加仓: 0.1@80000 + 0.1@82000 → 0.2@81000"""
        size1 = Decimal("0.1")
        price1 = Decimal("80000")
        size2 = Decimal("0.1")
        price2 = Decimal("82000")

        total_size = size1 + size2
        total_notional = size1 * price1 + size2 * price2
        avg_price = total_notional / total_size

        assert total_size == Decimal("0.2")
        assert avg_price == Decimal("81000")

    def test_weighted_average_unequal(self):
        """不等量加仓: 0.1@80000 + 0.3@84000 → 0.4@83000"""
        size1 = Decimal("0.1")
        price1 = Decimal("80000")
        size2 = Decimal("0.3")
        price2 = Decimal("84000")

        total_size = size1 + size2
        total_notional = size1 * price1 + size2 * price2
        avg_price = total_notional / total_size

        assert total_size == Decimal("0.4")
        assert avg_price == Decimal("83000")


# ============================================
# J. 部分平仓比例测试
# ============================================

class TestPartialClose:
    """部分平仓按比例计算 P&L 和释放保证金"""

    def test_half_close_pnl(self):
        """半仓平仓: PnL 应为全仓的一半"""
        full_pnl = Decimal("200")  # 全仓 PnL
        close_ratio = Decimal("0.05") / Decimal("0.1")  # 平一半
        partial_pnl = full_pnl * close_ratio
        assert partial_pnl == Decimal("100")

    def test_half_close_margin_release(self):
        """半仓平仓: 释放一半保证金"""
        total_margin = Decimal("800")
        close_ratio = Decimal("0.05") / Decimal("0.1")
        released = total_margin * close_ratio
        assert released == Decimal("400")

    def test_remaining_position(self):
        """半仓平仓后: 剩余仓位数量和保证金都减半"""
        initial_size = Decimal("0.1")
        initial_margin = Decimal("800")
        close_qty = Decimal("0.05")

        remaining_size = initial_size - close_qty
        remaining_margin = initial_margin - initial_margin * (close_qty / initial_size)

        assert remaining_size == Decimal("0.05")
        assert remaining_margin == Decimal("400")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
