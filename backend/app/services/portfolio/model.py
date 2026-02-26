"""
Portfolio Model — 仓位计算层
==============================
LEAN 风格: Portfolio Model 负责将 Insight → PortfolioTarget (仓位目标)

职责:
1. 接收 Insight (信号方向 + 信心)
2. 结合账户状态 (余额、已有持仓)
3. 计算最优仓位 (数量、杠杆、止损止盈)
4. 输出 PortfolioTarget

设计原则:
- Portfolio 可以拒绝 Insight (如余额不足)
- 一个 Insight 最多产生一个 Target
- Target 还需要通过 Risk Model 审批
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.alpha.base import Insight, InsightDirection


# ============================================================
# PortfolioTarget — Portfolio 的唯一输出
# ============================================================

class TargetAction(str, Enum):
    """仓位目标动作"""
    OPEN_LONG   = "open_long"     # 开多
    OPEN_SHORT  = "open_short"    # 开空
    CLOSE       = "close"         # 平仓
    INCREASE    = "increase"      # 加仓
    REDUCE      = "reduce"        # 减仓


@dataclass
class PortfolioTarget:
    """
    仓位目标 — Portfolio Model 的唯一输出
    
    包含完整的交易参数:
    - 品种、方向、数量
    - 杠杆、止损、止盈
    - 保证金、预估手续费
    
    投资到 Risk Model 审批, 审批通过后由 Execution 执行。
    """
    symbol: str                             # "ETHUSDT"
    action: TargetAction                    # OPEN_LONG / OPEN_SHORT / CLOSE
    quantity: Decimal                       # 下单数量
    leverage: int                           # 杠杆倍数
    
    # 订单参数 (支持所有订单类型)
    order_type: str = "market"              # market / limit / stop_market ...
    price: Optional[Decimal] = None         # 限价单价格
    trigger_price: Optional[Decimal] = None # 止损/止盈触发价
    position_side: Optional[str] = None     # long / short / both
    reduce_only: bool = False               # 只减仓
    
    # 风控参数
    stop_loss_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None
    
    # 财务
    notional: Decimal = Decimal("0")        # 名义价值
    required_margin: Decimal = Decimal("0") # 所需保证金
    estimated_fee: Decimal = Decimal("0")   # 预估手续费
    
    # 来源追踪
    insight: Optional[Insight] = None       # 触发此 Target 的 Insight
    source: str = ""                        # 来源
    
    # 元数据
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_cost(self) -> Decimal:
        """总成本 = 保证金 + 手续费"""
        return self.required_margin + self.estimated_fee
    
    def summary(self) -> str:
        side = "📈多" if self.action == TargetAction.OPEN_LONG else "📉空"
        return (
            f"{side} {self.symbol} qty={self.quantity} "
            f"leverage={self.leverage}x margin={self.required_margin:.2f}"
        )
    
    def __repr__(self) -> str:
        return f"<Target({self.summary()})>"


# ============================================================
# PortfolioModel — 仓位计算基类
# ============================================================

class PortfolioModel(ABC):
    """
    Portfolio 模型基类
    
    子类实现:
    - calculate_target(): 将 Insight + 账户状态 → PortfolioTarget
    """
    
    @abstractmethod
    async def calculate_target(
        self,
        insight: Insight,
        current_price: Decimal,
        available_balance: Decimal,
        existing_positions: list,
        **kwargs,
    ) -> Optional[PortfolioTarget]:
        """
        核心方法 — 计算仓位目标
        
        Args:
            insight: Alpha 信号
            current_price: 当前价格
            available_balance: 可用余额 (USDT)
            existing_positions: 已有持仓列表
        
        Returns:
            PortfolioTarget or None (决定不交易)
        """
        ...
    
    @staticmethod
    def _compute_sl_tp(
        entry_price: Decimal,
        direction: InsightDirection,
        sl_pct: float = 2.0,
        tp_pct: float = 4.0,
    ) -> tuple:
        """计算止损止盈价格"""
        sl_pct_dec = Decimal(str(sl_pct)) / Decimal("100")
        tp_pct_dec = Decimal(str(tp_pct)) / Decimal("100")
        
        if direction == InsightDirection.UP:
            sl = entry_price * (Decimal("1") - sl_pct_dec)
            tp = entry_price * (Decimal("1") + tp_pct_dec)
        else:
            sl = entry_price * (Decimal("1") + sl_pct_dec)
            tp = entry_price * (Decimal("1") - tp_pct_dec)
        
        return sl, tp


# ============================================================
# FixedPercentModel — 固定比例仓位管理
# ============================================================

class FixedPercentModel(PortfolioModel):
    """
    固定比例仓位模型
    
    每次用可用余额的固定比例开仓 (默认 10%)
    简单可靠, 适合大多数场景
    """
    
    def __init__(
        self,
        risk_percent: float = 10.0,     # 每次使用余额的 10%
        default_leverage: int = 5,      # 默认杠杆
        max_positions: int = 5,         # 最大持仓数
        default_sl_pct: float = 2.0,    # 默认止损 2%
        default_tp_pct: float = 4.0,    # 默认止盈 4%
    ):
        self._risk_percent = risk_percent
        self._default_leverage = default_leverage
        self._max_positions = max_positions
        self._default_sl_pct = default_sl_pct
        self._default_tp_pct = default_tp_pct
    
    async def calculate_target(
        self,
        insight: Insight,
        current_price: Decimal,
        available_balance: Decimal,
        existing_positions: list,
        **kwargs,
    ) -> Optional[PortfolioTarget]:
        
        # 1. 检查最大持仓数
        if len(existing_positions) >= self._max_positions:
            logger.warning(
                f"[Portfolio:FixedPercent] Max positions {self._max_positions} reached, skip"
            )
            return None
        
        # 2. 检查是否已有同方向持仓
        for pos in existing_positions:
            if pos.get("symbol") == insight.symbol:
                pos_side = pos.get("side", "")
                if (
                    (insight.direction == InsightDirection.UP and pos_side == "long") or
                    (insight.direction == InsightDirection.DOWN and pos_side == "short")
                ):
                    logger.info(
                        f"[Portfolio:FixedPercent] Already have {pos_side} "
                        f"position on {insight.symbol}, skip"
                    )
                    return None
        
        # 3. 计算保证金
        leverage = insight.suggested_leverage or self._default_leverage
        margin = available_balance * Decimal(str(self._risk_percent)) / Decimal("100")
        
        # 最低保证金检查
        from app.models.security import security_manager
        spec = security_manager.get_or_default(insight.symbol)
        
        min_margin = spec.min_notional / Decimal(str(leverage))
        if margin < min_margin:
            logger.warning(
                f"[Portfolio:FixedPercent] Margin {margin:.2f} < min {min_margin:.2f} "
                f"for {insight.symbol}"
            )
            return None
        
        # 4. 计算数量
        notional = margin * Decimal(str(leverage))
        quantity = notional / current_price
        
        # 按精度取整
        quantity = security_manager.round_quantity(insight.symbol, quantity)
        
        if quantity <= 0:
            return None
        
        # 重算名义和保证金
        notional = quantity * current_price
        margin = notional / Decimal(str(leverage))
        
        # 5. 止损止盈
        sl_pct = insight.suggested_stop_loss_pct or self._default_sl_pct
        tp_pct = insight.suggested_take_profit_pct or self._default_tp_pct
        sl, tp = self._compute_sl_tp(current_price, insight.direction, sl_pct, tp_pct)
        
        # 6. 手续费估算
        fee = security_manager.estimate_commission(insight.symbol, quantity, current_price)
        
        action = (
            TargetAction.OPEN_LONG
            if insight.direction == InsightDirection.UP
            else TargetAction.OPEN_SHORT
        )
        
        target = PortfolioTarget(
            symbol=insight.symbol,
            action=action,
            quantity=quantity,
            leverage=leverage,
            stop_loss_price=sl,
            take_profit_price=tp,
            notional=notional,
            required_margin=margin,
            estimated_fee=fee,
            insight=insight,
            source="portfolio:fixed_percent",
        )
        
        logger.info(f"[Portfolio:FixedPercent] {target.summary()}")
        return target


# ============================================================
# KellyPortfolioModel — 凯利公式仓位管理
# ============================================================

class KellyPortfolioModel(PortfolioModel):
    """
    凯利公式 (Kelly Criterion) 仓位管理
    
    f* = (p × b - q) / b
    
    其中:
    - p = 胜率 (用 insight.confidence 近似)
    - q = 败率 (1 - p)  
    - b = 赔率 (用 TP/SL 比近似)
    
    安全措施:
    - 使用 Half-Kelly (f* / 2) 降低波动
    - 最大仓位限制 (余额的 25%)
    """
    
    def __init__(
        self,
        kelly_fraction: float = 0.5,    # Half-Kelly
        max_risk_percent: float = 25.0, # 最大不超过余额的 25%
        default_leverage: int = 5,
        odds_ratio: float = 2.0,        # 默认赔率 (TP 是 SL 的 2 倍)
        max_positions: int = 5,
        default_sl_pct: float = 2.0,
        default_tp_pct: float = 4.0,
    ):
        self._kelly_fraction = kelly_fraction
        self._max_risk_percent = max_risk_percent
        self._default_leverage = default_leverage
        self._odds_ratio = odds_ratio
        self._max_positions = max_positions
        self._default_sl_pct = default_sl_pct
        self._default_tp_pct = default_tp_pct
    
    async def calculate_target(
        self,
        insight: Insight,
        current_price: Decimal,
        available_balance: Decimal,
        existing_positions: list,
        **kwargs,
    ) -> Optional[PortfolioTarget]:
        
        # 1. 持仓检查 (同 FixedPercent)
        if len(existing_positions) >= self._max_positions:
            logger.warning(
                f"[Portfolio:Kelly] Max positions {self._max_positions} reached"
            )
            return None
        
        for pos in existing_positions:
            if pos.get("symbol") == insight.symbol:
                pos_side = pos.get("side", "")
                if (
                    (insight.direction == InsightDirection.UP and pos_side == "long") or
                    (insight.direction == InsightDirection.DOWN and pos_side == "short")
                ):
                    return None
        
        # 2. 凯利公式
        p = insight.confidence                    # 胜率近似
        q = 1.0 - p
        b = self._odds_ratio                      # 赔率
        
        kelly_f = (p * b - q) / b if b > 0 else 0
        
        # 安全限制
        kelly_f = max(0, kelly_f)                  # 不做负值 (不反向)
        kelly_f *= self._kelly_fraction            # Half-Kelly
        kelly_f = min(kelly_f, self._max_risk_percent / 100)
        
        if kelly_f < 0.01:  # 仓位太小
            logger.debug(
                f"[Portfolio:Kelly] {insight.symbol} kelly_f={kelly_f:.4f} too small, skip"
            )
            return None
        
        # 3. 计算保证金
        leverage = insight.suggested_leverage or self._default_leverage
        margin = available_balance * Decimal(str(kelly_f))
        
        # 最低保证金检查
        from app.models.security import security_manager
        spec = security_manager.get_or_default(insight.symbol)
        
        min_margin = spec.min_notional / Decimal(str(leverage))
        if margin < min_margin:
            return None
        
        # 4. 数量
        notional = margin * Decimal(str(leverage))
        quantity = notional / current_price
        quantity = security_manager.round_quantity(insight.symbol, quantity)
        
        if quantity <= 0:
            return None
        
        notional = quantity * current_price
        margin = notional / Decimal(str(leverage))
        
        # 5. 止损止盈
        sl_pct = insight.suggested_stop_loss_pct or self._default_sl_pct
        tp_pct = insight.suggested_take_profit_pct or self._default_tp_pct
        sl, tp = self._compute_sl_tp(current_price, insight.direction, sl_pct, tp_pct)
        
        # 6. 手续费
        fee = security_manager.estimate_commission(insight.symbol, quantity, current_price)
        
        action = (
            TargetAction.OPEN_LONG
            if insight.direction == InsightDirection.UP
            else TargetAction.OPEN_SHORT
        )
        
        target = PortfolioTarget(
            symbol=insight.symbol,
            action=action,
            quantity=quantity,
            leverage=leverage,
            stop_loss_price=sl,
            take_profit_price=tp,
            notional=notional,
            required_margin=margin,
            estimated_fee=fee,
            insight=insight,
            source="portfolio:kelly",
            metadata={
                "kelly_f": round(kelly_f, 4),
                "confidence": insight.confidence,
                "odds_ratio": self._odds_ratio,
            },
        )
        
        logger.info(
            f"[Portfolio:Kelly] {target.summary()} "
            f"(kelly_f={kelly_f:.4f}, confidence={insight.confidence:.2f})"
        )
        return target
