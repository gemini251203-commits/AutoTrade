"""
Risk Model — 风控审批层
========================
LEAN 风格: Risk Model 作为 Pipeline 的守门员

职责:
1. 预审批 PortfolioTarget (在下单前拦截)
2. 持续监控 (强平/止损/日亏损限额)
3. 紧急熔断 (一票否决)

与现有 RiskEngine 的关系:
- RiskEngine 保持不变 (计算层: 盈亏、保证金率、强平价)
- RiskModel 新增审批层 (决策层: 是否允许交易)
"""

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Optional

from loguru import logger

from app.services.portfolio.model import PortfolioTarget, TargetAction


# ============================================================
# 风控配置
# ============================================================

@dataclass
class RiskConfig:
    """风控参数配置"""
    
    # 单笔限制
    max_leverage: int = 20                              # 最大杠杆
    max_single_margin_pct: float = 30.0                 # 单笔最大保证金 (占余额%)
    max_notional: Decimal = Decimal("50000")            # 单笔最大名义价值
    
    # 账户限制
    max_positions: int = 10                             # 最大持仓数
    max_daily_loss_pct: float = 10.0                    # 日最大亏损 (占权益%)
    max_total_exposure_pct: float = 200.0               # 最大总敞口 (占权益%)
    
    # 品种限制
    blacklist: list = None                              # 禁止交易的品种
    
    def __post_init__(self):
        if self.blacklist is None:
            self.blacklist = []


# ============================================================
# 审批结果
# ============================================================

@dataclass
class RiskVerdict:
    """风控审批结果"""
    approved: bool                          # 是否通过
    reason: str = ""                        # 拒绝原因
    warnings: list = None                   # 警告 (通过但需注意)
    adjusted_target: Optional[PortfolioTarget] = None  # 调整后的 Target
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# ============================================================
# RiskModel
# ============================================================

class RiskModel:
    """
    风控模型 — 四层流水线的守门员
    
    两个核心功能:
    1. approve_target(): 预审批交易目标
    2. monitor_continuous(): 持续监控 (由 EventBus TICK 触发)
    """
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self._config = config or RiskConfig()
        self._daily_pnl: Dict[int, Decimal] = {}           # user_id → 当日 PnL
        self._daily_reset_date: Optional[date] = None
        self._circuit_breaker: bool = False                  # 紧急熔断
    
    # ----------------------------------------------------------
    # 1. 预审批 Target
    # ----------------------------------------------------------
    
    async def approve_target(
        self,
        target: PortfolioTarget,
        available_balance: Decimal,
        total_equity: Decimal,
        open_positions: list,
        user_id: int = 0,
    ) -> RiskVerdict:
        """
        审批 PortfolioTarget — 在下单前最后一道防线
        
        检查顺序:
        1. 熔断检查
        2. 黑名单
        3. 杠杆限制
        4. 保证金限制
        5. 名义价值限制
        6. 持仓数限制
        7. 日亏损限制
        8. 总敞口限制
        """
        warnings = []
        
        # — 紧急熔断 —
        if self._circuit_breaker:
            return RiskVerdict(
                approved=False,
                reason="🚨 风控熔断中, 禁止一切交易"
            )
        
        # — 黑名单 —
        if target.symbol in self._config.blacklist:
            return RiskVerdict(
                approved=False,
                reason=f"{target.symbol} 在黑名单中"
            )
        
        # — 杠杆限制 —
        if target.leverage > self._config.max_leverage:
            return RiskVerdict(
                approved=False,
                reason=(
                    f"杠杆 {target.leverage}x 超过最大限制 "
                    f"{self._config.max_leverage}x"
                )
            )
        
        # — 保证金限制 —
        if available_balance > 0:
            margin_pct = float(target.required_margin / available_balance * 100)
            if margin_pct > self._config.max_single_margin_pct:
                return RiskVerdict(
                    approved=False,
                    reason=(
                        f"单笔保证金 {target.required_margin:.2f} "
                        f"({margin_pct:.1f}%) 超过限制 "
                        f"{self._config.max_single_margin_pct}%"
                    )
                )
            if margin_pct > self._config.max_single_margin_pct * 0.8:
                warnings.append(
                    f"保证金占比较高: {margin_pct:.1f}%"
                )
        
        # — 名义价值限制 —
        if target.notional > self._config.max_notional:
            return RiskVerdict(
                approved=False,
                reason=(
                    f"名义价值 {target.notional:.2f} "
                    f"超过限制 {self._config.max_notional}"
                )
            )
        
        # — 持仓数限制 —
        if len(open_positions) >= self._config.max_positions:
            return RiskVerdict(
                approved=False,
                reason=f"持仓数 {len(open_positions)} 已达上限 {self._config.max_positions}"
            )
        
        # — 日亏损限制 —
        self._reset_daily_if_needed()
        daily_loss = self._daily_pnl.get(user_id, Decimal("0"))
        if total_equity > 0 and daily_loss < 0:
            loss_pct = float(abs(daily_loss) / total_equity * 100)
            if loss_pct >= self._config.max_daily_loss_pct:
                return RiskVerdict(
                    approved=False,
                    reason=(
                        f"日亏损 {loss_pct:.1f}% 已达限制 "
                        f"{self._config.max_daily_loss_pct}%"
                    )
                )
            if loss_pct >= self._config.max_daily_loss_pct * 0.8:
                warnings.append(
                    f"⚠️ 日亏损已达 {loss_pct:.1f}%, 接近限制"
                )
        
        # — 总敞口限制 —
        total_notional = sum(
            Decimal(str(p.get("notional", 0))) for p in open_positions
        )
        new_total = total_notional + target.notional
        if total_equity > 0:
            exposure_pct = float(new_total / total_equity * 100)
            if exposure_pct > self._config.max_total_exposure_pct:
                return RiskVerdict(
                    approved=False,
                    reason=(
                        f"总敞口 {exposure_pct:.1f}% "
                        f"超过限制 {self._config.max_total_exposure_pct}%"
                    )
                )
        
        # ✅ 通过
        logger.info(
            f"[RiskModel] ✅ Approved: {target.summary()}"
            + (f" warnings: {warnings}" if warnings else "")
        )
        
        return RiskVerdict(
            approved=True,
            warnings=warnings,
        )
    
    # ----------------------------------------------------------
    # 2. 持续监控 (由 EventBus TICK 触发)
    # ----------------------------------------------------------
    
    def update_daily_pnl(self, user_id: int, realized_pnl: Decimal) -> None:
        """更新用户当日 PnL"""
        self._reset_daily_if_needed()
        current = self._daily_pnl.get(user_id, Decimal("0"))
        self._daily_pnl[user_id] = current + realized_pnl
    
    # ----------------------------------------------------------
    # 3. 紧急熔断
    # ----------------------------------------------------------
    
    def trigger_circuit_breaker(self, reason: str = "") -> None:
        """触发紧急熔断 — 禁止所有交易"""
        self._circuit_breaker = True
        logger.critical(
            f"[RiskModel] 🚨 CIRCUIT BREAKER TRIGGERED: {reason}"
        )
    
    def reset_circuit_breaker(self) -> None:
        """解除熔断"""
        self._circuit_breaker = False
        logger.warning("[RiskModel] Circuit breaker RESET")
    
    @property
    def is_circuit_breaker_active(self) -> bool:
        return self._circuit_breaker
    
    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------
    
    def _reset_daily_if_needed(self) -> None:
        """跨日重置"""
        today = date.today()
        if self._daily_reset_date != today:
            self._daily_pnl.clear()
            self._daily_reset_date = today
