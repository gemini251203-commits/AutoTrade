"""
Margin Calculator Service
==========================
保证金计算服务

支持逐仓(Isolated)和全仓(Cross)两种保证金模式的币安级别计算。
"""

from decimal import Decimal
from typing import Optional, Tuple
from enum import Enum

from app.models.position import PositionSide, MarginMode
from app.services.margin.leverage_tiers import (
    get_max_leverage,
    get_maintenance_margin_rate,
    validate_leverage,
    MIN_NOTIONAL_VALUE,
)


class MarginCalculator:
    """
    保证金计算器 - 币安级别公式
    
    逐仓模式 (Isolated):
    - 每个仓位独立保证金
    - 强平价格固定，开仓后不变
    - 爆仓只影响该仓位
    
    全仓模式 (Cross):
    - 所有仓位共享账户余额作为保证金
    - 强平价格动态变化，根据账户权益实时计算
    - 仓位盈利可以给其他仓位"补血"
    """
    
    # 币安默认维持保证金率 (不同杠杆档位不同，这里使用基础档)
    DEFAULT_MAINTENANCE_MARGIN_RATE = Decimal("0.004")  # 0.4%
    
    @staticmethod
    def calculate_margin(
        quantity: Decimal,
        price: Decimal,
        leverage: int
    ) -> Decimal:
        """
        计算开仓所需保证金
        
        公式: 保证金 = (数量 × 价格) / 杠杆
        
        例: 买入 0.1 BTC @ $78,000, 50x 杠杆
        保证金 = (0.1 × 78000) / 50 = 156 USDT
        
        Args:
            quantity: 开仓数量 (BTC)
            price: 开仓价格 (USDT)
            leverage: 杠杆倍数
            
        Returns:
            所需保证金 (USDT)
        """
        notional_value = quantity * price
        return (notional_value / Decimal(leverage)).quantize(Decimal("0.00000001"))
    
    @staticmethod
    def calculate_isolated_liquidation_price(
        entry_price: Decimal,
        leverage: int,
        side: PositionSide,
        maintenance_margin_rate: Decimal = None
    ) -> Decimal:
        """
        计算逐仓模式强平价格 (固定值)
        
        做多公式: 强平价 = 开仓价 × (1 - 1/杠杆 + 维持保证金率)
        做空公式: 强平价 = 开仓价 × (1 + 1/杠杆 - 维持保证金率)
        
        例 (50x 做多 @ 78000):
        强平价 = 78000 × (1 - 0.02 + 0.004) = 78000 × 0.984 = 76,752
        
        Args:
            entry_price: 开仓价格
            leverage: 杠杆倍数
            side: 仓位方向 (LONG/SHORT)
            maintenance_margin_rate: 维持保证金率 (默认0.4%)
            
        Returns:
            强平价格
        """
        if maintenance_margin_rate is None:
            maintenance_margin_rate = MarginCalculator.DEFAULT_MAINTENANCE_MARGIN_RATE
            
        lev = Decimal(leverage)
        one = Decimal("1")
        
        if side == PositionSide.LONG:
            # 做多: 价格下跌到此价位爆仓
            liq_price = entry_price * (one - one/lev + maintenance_margin_rate)
        else:
            # 做空: 价格上涨到此价位爆仓
            liq_price = entry_price * (one + one/lev - maintenance_margin_rate)
        
        return liq_price.quantize(Decimal("0.01"))
    
    @staticmethod
    def calculate_cross_liquidation_price(
        entry_price: Decimal,
        quantity: Decimal,
        position_margin: Decimal,
        account_balance: Decimal,
        unrealized_pnl: Decimal,
        other_positions_margin: Decimal,
        side: PositionSide,
        maintenance_margin_rate: Decimal = None
    ) -> Decimal:
        """
        计算全仓模式强平价格 (动态值)
        
        全仓模式下，账户的所有可用余额（包括未实现盈亏）都作为保证金。
        
        账户权益 = 账户余额 + 所有仓位未实现盈亏
        可用保证金 = 账户权益 - 其他仓位占用保证金
        
        做多强平公式:
        强平价 = 开仓价 × (1 - 可用保证金/(数量×开仓价) + 维持保证金率)
        
        做空强平公式:
        强平价 = 开仓价 × (1 + 可用保证金/(数量×开仓价) - 维持保证金率)
        
        Args:
            entry_price: 开仓价格
            quantity: 仓位数量
            position_margin: 该仓位占用的初始保证金
            account_balance: 账户余额 (钱包余额 + 冻结资金)
            unrealized_pnl: 所有仓位的未实现盈亏总和
            other_positions_margin: 其他仓位占用的保证金总和
            side: 仓位方向
            maintenance_margin_rate: 维持保证金率
            
        Returns:
            动态强平价格
        """
        if maintenance_margin_rate is None:
            maintenance_margin_rate = MarginCalculator.DEFAULT_MAINTENANCE_MARGIN_RATE
        
        one = Decimal("1")
        
        # 账户总权益
        total_equity = account_balance + unrealized_pnl
        
        # 可用于该仓位的保证金 = 总权益 - 其他仓位保证金
        available_margin = total_equity - other_positions_margin
        
        # 仓位名义价值
        notional = quantity * entry_price
        
        if notional == 0:
            return Decimal("0")
        
        # 保证金比率
        margin_ratio = available_margin / notional
        
        if side == PositionSide.LONG:
            # 全仓做多: 强平价格会更低（因为有更多保证金支撑）
            liq_price = entry_price * (one - margin_ratio + maintenance_margin_rate)
        else:
            # 全仓做空: 强平价格会更高
            liq_price = entry_price * (one + margin_ratio - maintenance_margin_rate)
        
        # 确保强平价不为负
        if liq_price < 0:
            liq_price = Decimal("0")
            
        return liq_price.quantize(Decimal("0.01"))
    
    @staticmethod
    def calculate_unrealized_pnl(
        side: PositionSide,
        quantity: Decimal,
        entry_price: Decimal,
        current_price: Decimal
    ) -> Decimal:
        """
        计算未实现盈亏
        
        做多: PNL = (当前价 - 开仓价) × 数量
        做空: PNL = (开仓价 - 当前价) × 数量
        
        Args:
            side: 仓位方向
            quantity: 仓位数量
            entry_price: 开仓价格
            current_price: 当前市场价格
            
        Returns:
            未实现盈亏 (正数为盈利，负数为亏损)
        """
        if side == PositionSide.LONG:
            return (current_price - entry_price) * quantity
        else:
            return (entry_price - current_price) * quantity
    
    @staticmethod
    def calculate_margin_ratio(
        position_margin: Decimal,
        unrealized_pnl: Decimal,
        maintenance_margin: Decimal
    ) -> Decimal:
        """
        计算保证金率 (用于判断是否接近强平)
        
        保证金率 = 维持保证金 / (保证金 + 未实现盈亏)
        
        当保证金率 >= 100% 时触发强平
        
        Args:
            position_margin: 仓位保证金
            unrealized_pnl: 未实现盈亏
            maintenance_margin: 维持保证金
            
        Returns:
            保证金率 (百分比，如 0.25 表示 25%)
        """
        equity = position_margin + unrealized_pnl
        
        if equity <= 0:
            return Decimal("999")  # 已爆仓
            
        return (maintenance_margin / equity).quantize(Decimal("0.0001"))
    
    # ============================================
    # 杠杆档位验证 (新增)
    # ============================================
    
    @staticmethod
    def validate_order_leverage(
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        leverage: int
    ) -> Tuple[bool, Optional[str], int]:
        """
        验证订单杠杆是否符合币安规则
        
        Args:
            symbol: 交易对 (如 BTCUSDT)
            quantity: 数量
            price: 价格
            leverage: 请求的杠杆
            
        Returns:
            Tuple[is_valid, error_message, max_allowed_leverage]
        """
        notional = quantity * price
        return validate_leverage(symbol, notional, leverage)
    
    @staticmethod
    def get_dynamic_maintenance_margin_rate(
        symbol: str,
        quantity: Decimal,
        price: Decimal
    ) -> Decimal:
        """
        获取动态维持保证金率 (根据仓位大小)
        
        Args:
            symbol: 交易对
            quantity: 数量
            price: 价格
            
        Returns:
            维持保证金率
        """
        notional = quantity * price
        return get_maintenance_margin_rate(symbol, notional)
    
    @staticmethod
    def get_max_leverage_for_order(
        symbol: str,
        quantity: Decimal,
        price: Decimal
    ) -> int:
        """
        获取订单允许的最大杠杆
        
        Args:
            symbol: 交易对
            quantity: 数量
            price: 价格
            
        Returns:
            最大杠杆倍数
        """
        notional = quantity * price
        return get_max_leverage(symbol, notional)
    
    # ============================================
    # 止盈止损盈亏预览 (新增)
    # ============================================
    
    @staticmethod
    def calculate_tp_sl_preview(
        side: PositionSide,
        quantity: Decimal,
        entry_price: Decimal,
        take_profit: Optional[Decimal],
        stop_loss: Optional[Decimal],
        leverage: int = 1
    ) -> dict:
        """
        计算止盈止损的预计盈亏
        
        Args:
            side: 仓位方向
            quantity: 数量
            entry_price: 入场价格
            take_profit: 止盈价格
            stop_loss: 止损价格
            leverage: 杠杆 (仅用于计算收益率)
            
        Returns:
            {
                "take_profit_pnl": Decimal,      # 止盈盈亏 (USDT)
                "take_profit_pct": Decimal,      # 止盈收益率 (%)
                "stop_loss_pnl": Decimal,        # 止损盈亏 (USDT)
                "stop_loss_pct": Decimal,        # 止损收益率 (%)
                "risk_reward_ratio": Decimal,    # 风险回报比
            }
        """
        result = {
            "take_profit_pnl": Decimal("0"),
            "take_profit_pct": Decimal("0"),
            "stop_loss_pnl": Decimal("0"),
            "stop_loss_pct": Decimal("0"),
            "risk_reward_ratio": Decimal("0"),
        }
        
        notional = quantity * entry_price
        margin = notional / Decimal(leverage)
        
        # 计算止盈盈亏
        if take_profit and take_profit > 0:
            if side == PositionSide.LONG:
                tp_pnl = (take_profit - entry_price) * quantity
            else:
                tp_pnl = (entry_price - take_profit) * quantity
            
            result["take_profit_pnl"] = tp_pnl.quantize(Decimal("0.01"))
            if margin > 0:
                result["take_profit_pct"] = ((tp_pnl / margin) * 100).quantize(Decimal("0.01"))
        
        # 计算止损盈亏
        if stop_loss and stop_loss > 0:
            if side == PositionSide.LONG:
                sl_pnl = (stop_loss - entry_price) * quantity
            else:
                sl_pnl = (entry_price - stop_loss) * quantity
            
            result["stop_loss_pnl"] = sl_pnl.quantize(Decimal("0.01"))
            if margin > 0:
                result["stop_loss_pct"] = ((sl_pnl / margin) * 100).quantize(Decimal("0.01"))
        
        # 计算风险回报比
        if result["stop_loss_pnl"] != 0 and result["stop_loss_pnl"] < 0:
            risk = abs(result["stop_loss_pnl"])
            reward = result["take_profit_pnl"]
            if risk > 0:
                result["risk_reward_ratio"] = (reward / risk).quantize(Decimal("0.01"))
        
        return result

