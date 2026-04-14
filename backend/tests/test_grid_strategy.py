"""
网格策略(Grid Strategy)单元测试
===================================
测试网格价格计算的纯数学逻辑 (等差/等比网格)。

纯单元测试, 不依赖数据库和网络请求。

运行方式:
    cd backend
    python -m pytest tests/test_grid_strategy.py -v
"""

import sys
import os
import importlib
import importlib.util
import types
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
import pytest

# --- Mock 重依赖模块，使 grid/strategy.py 可在无 DB 环境下加载 ---

# Mock GridType / GridStatus / GridDirection 枚举 (原定义在 models/grid_bot.py, 需要 SQLAlchemy DB)
class GridType(str, Enum):
    ARITHMETIC = "arithmetic"
    GEOMETRIC = "geometric"

class GridStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"

class GridDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"

# 创建 mock 模块层级
for mod_name in ["app", "app.models", "app.models.grid_bot",
                  "app.models.order", "app.services", "app.services.trading",
                  "app.services.wallet", "app.services.trade_journal",
                  "app.core", "app.core.time_utils", "app.db", "app.db.base"]:
    sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

# 注入枚举到 mock 模块
sys.modules["app.models.grid_bot"].GridBot = type("GridBot", (), {})
sys.modules["app.models.grid_bot"].GridType = GridType
sys.modules["app.models.grid_bot"].GridStatus = GridStatus
sys.modules["app.models.grid_bot"].GridDirection = GridDirection
sys.modules["app.models.order"].Order = type("Order", (), {})
sys.modules["app.models.order"].OrderSide = type("OrderSide", (), {"BUY": "buy", "SELL": "sell"})
sys.modules["app.models.order"].OrderType = type("OrderType", (), {"LIMIT": "limit"})
sys.modules["app.models.order"].OrderStatus = type("OrderStatus", (), {})
sys.modules["app.services.trading"].OrderExecutor = type("OrderExecutor", (), {})
sys.modules["app.services.trading"].OrderError = Exception
sys.modules["app.services.wallet"].WalletManager = type("WalletManager", (), {})
sys.modules["app.services.trade_journal"].TradeJournal = type("TradeJournal", (), {})
sys.modules["app.core.time_utils"].utc_now = lambda: None
sys.modules["app.db.base"].Base = type("Base", (), {})

# 加载 strategy.py
_mod_path = os.path.join(os.path.dirname(__file__), "..", "app", "services", "grid", "strategy.py")
_spec = importlib.util.spec_from_file_location("grid_strategy", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

GridStrategy = _mod.GridStrategy


# ============================================
# A. 等差网格价格计算
# ============================================

class TestArithmeticGrid:
    """等差网格: 每格间距相等"""

    def test_basic_10_grids(self):
        """10 格等差: [80000, 90000] → 11 个价格点, 间距 1000"""
        prices, interval = GridStrategy.calculate_grid_prices(
            lower_price=Decimal("80000"),
            upper_price=Decimal("90000"),
            grid_count=10,
            grid_type=GridType.ARITHMETIC,
        )
        assert len(prices) == 11  # 10 格 = 11 个价格点
        assert prices[0] == Decimal("80000.00")
        assert prices[-1] == Decimal("90000.00")
        assert interval == Decimal("1000")

    def test_equal_spacing(self):
        """等差网格所有间距相等"""
        prices, interval = GridStrategy.calculate_grid_prices(
            lower_price=Decimal("1000"),
            upper_price=Decimal("2000"),
            grid_count=5,
            grid_type=GridType.ARITHMETIC,
        )
        for i in range(1, len(prices)):
            spacing = prices[i] - prices[i - 1]
            assert abs(spacing - Decimal("200")) < Decimal("0.1")

    def test_2_grids_minimum(self):
        """最小 2 格: 产生 3 个价格点"""
        prices, interval = GridStrategy.calculate_grid_prices(
            lower_price=Decimal("100"),
            upper_price=Decimal("200"),
            grid_count=2,
            grid_type=GridType.ARITHMETIC,
        )
        assert len(prices) == 3
        assert prices[0] == Decimal("100.00")
        assert prices[1] == Decimal("150.00")
        assert prices[2] == Decimal("200.00")

    def test_first_equals_lower(self):
        """第一个价格 = 下边界"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("50000"), Decimal("60000"), 5, GridType.ARITHMETIC
        )
        assert prices[0] == Decimal("50000.00")

    def test_last_equals_upper(self):
        """最后一个价格 = 上边界"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("50000"), Decimal("60000"), 5, GridType.ARITHMETIC
        )
        assert prices[-1] == Decimal("60000.00")

    def test_prices_ascending(self):
        """所有价格严格递增"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("10000"), Decimal("20000"), 20, GridType.ARITHMETIC
        )
        for i in range(1, len(prices)):
            assert prices[i] > prices[i - 1]


# ============================================
# B. 等比网格价格计算
# ============================================

class TestGeometricGrid:
    """等比网格: 每格涨跌相同百分比"""

    def test_basic_geometric(self):
        """等比网格: 价格点数量正确"""
        prices, interval = GridStrategy.calculate_grid_prices(
            lower_price=Decimal("80000"),
            upper_price=Decimal("100000"),
            grid_count=10,
            grid_type=GridType.GEOMETRIC,
        )
        assert len(prices) == 11

    def test_first_last_correct(self):
        """等比网格: 首尾价格正确"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("1000"), Decimal("2000"), 5, GridType.GEOMETRIC
        )
        assert abs(prices[0] - Decimal("1000")) < Decimal("1")
        assert abs(prices[-1] - Decimal("2000")) < Decimal("1")

    def test_equal_percentage_spacing(self):
        """等比网格: 每格涨幅百分比近似相等"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("10000"), Decimal("20000"), 10, GridType.GEOMETRIC
        )
        ratios = []
        for i in range(1, len(prices)):
            ratio = float(prices[i]) / float(prices[i - 1])
            ratios.append(ratio)

        # 所有比率应该近似相等
        for r in ratios:
            assert abs(r - ratios[0]) < 0.001

    def test_prices_ascending(self):
        """等比网格价格严格递增"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("5000"), Decimal("50000"), 20, GridType.GEOMETRIC
        )
        for i in range(1, len(prices)):
            assert prices[i] > prices[i - 1]


# ============================================
# C. 每格数量计算
# ============================================

class TestQuantityPerGrid:
    """每格交易数量"""

    def test_basic_calculation(self):
        """基础: 10000 USDT, 10 格, 均价 80000, 1x → 每格 0.0125 BTC"""
        qty = GridStrategy.calculate_quantity_per_grid(
            investment=Decimal("10000"),
            grid_count=10,
            avg_price=Decimal("80000"),
            leverage=1,
        )
        # 每格投入 = 10000/10 = 1000
        # 名义价值 = 1000 * 1 = 1000
        # 数量 = 1000 / 80000 = 0.0125
        assert qty == Decimal("0.01250")

    def test_with_leverage(self):
        """杠杆放大: 同条件 10x → 数量 10 倍"""
        qty_1x = GridStrategy.calculate_quantity_per_grid(
            Decimal("10000"), 10, Decimal("80000"), 1
        )
        qty_10x = GridStrategy.calculate_quantity_per_grid(
            Decimal("10000"), 10, Decimal("80000"), 10
        )
        assert qty_10x == qty_1x * 10

    def test_more_grids_less_per_grid(self):
        """网格数增加，每格数量减少"""
        qty_5 = GridStrategy.calculate_quantity_per_grid(
            Decimal("10000"), 5, Decimal("80000"), 1
        )
        qty_20 = GridStrategy.calculate_quantity_per_grid(
            Decimal("10000"), 20, Decimal("80000"), 1
        )
        assert qty_20 < qty_5

    def test_precision_5_decimals(self):
        """数量精度为 5 位小数"""
        qty = GridStrategy.calculate_quantity_per_grid(
            Decimal("777"), 7, Decimal("12345.67"), 3
        )
        # 检查小数位数 ≤ 5
        str_qty = str(qty)
        if "." in str_qty:
            decimals = len(str_qty.split(".")[1])
            assert decimals <= 5


# ============================================
# D. 网格利润计算 (纯数学)
# ============================================

class TestGridProfit:
    """网格利润: 每次配对 = 卖出价 - 买入价"""

    def test_single_match_profit(self):
        """单次配对: 买@80000, 卖@81000, 数量 0.01 → 利润 $10"""
        buy_price = Decimal("80000")
        sell_price = Decimal("81000")
        quantity = Decimal("0.01")
        profit = (sell_price - buy_price) * quantity
        assert profit == Decimal("10")

    def test_grid_total_profit(self):
        """5 次配对, 每次利润 $10 → 总利润 $50"""
        single_profit = Decimal("10")
        match_count = 5
        total = single_profit * match_count
        assert total == Decimal("50")

    def test_arithmetic_grid_uniform_profit(self):
        """等差网格: 每次配对利润相同"""
        interval = Decimal("1000")  # 间距
        quantity = Decimal("0.01")

        profits = []
        for _ in range(5):
            profit = interval * quantity
            profits.append(profit)

        # 所有利润相同
        assert all(p == profits[0] for p in profits)

    def test_profit_net_of_commission(self):
        """扣除手续费后的净利润"""
        buy_price = Decimal("80000")
        sell_price = Decimal("81000")
        quantity = Decimal("0.01")

        gross_profit = (sell_price - buy_price) * quantity  # 10
        buy_commission = buy_price * quantity * Decimal("0.0005")  # 0.40
        sell_commission = sell_price * quantity * Decimal("0.0005")  # 0.405

        net_profit = gross_profit - buy_commission - sell_commission
        expected = Decimal("10") - Decimal("0.40") - Decimal("0.405")

        assert net_profit == expected
        assert net_profit > 0  # 利润大于手续费


# ============================================
# E. 边界情况
# ============================================

class TestGridEdgeCases:
    """网格边界情况"""

    def test_narrow_range(self):
        """窄区间: $100 范围, 100 格"""
        prices, interval = GridStrategy.calculate_grid_prices(
            Decimal("80000"), Decimal("80100"), 100, GridType.ARITHMETIC
        )
        assert len(prices) == 101
        assert interval == Decimal("1")

    def test_wide_range(self):
        """宽区间: $50000 范围"""
        prices, _ = GridStrategy.calculate_grid_prices(
            Decimal("50000"), Decimal("100000"), 50, GridType.ARITHMETIC
        )
        assert len(prices) == 51
        assert prices[0] == Decimal("50000.00")
        assert prices[-1] == Decimal("100000.00")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
