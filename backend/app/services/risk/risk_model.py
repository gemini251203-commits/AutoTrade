"""
Risk Model — 极简全局防爆层 (Sanity Check)
============================================
双层风控解耦后，RiskModel 只负责"账户级底线拦截"。

策略级风控（止损点位、仓位比例、盈亏比）由策略自行决定，
通过 TradingSignal 的 suggested_sl/tp/leverage 传达。

RiskModel 只检查两件事:
    a. 保证金可用率: 下单所需保证金 > 可用余额 → 拒绝
    b. 极端回撤熔断: 当日净值跌幅超阈值 → 拒绝新开仓

加上永远生效的:
    c. 紧急熔断 (circuit breaker): 一票否决
    d. 最大杠杆: Binance 交易所级限制
    e. 黑名单: 禁止交易品种
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple

from loguru import logger

from app.services.portfolio.model import PortfolioTarget, TargetAction


# ============================================================
# 风控配置 (极简化)
# ============================================================

@dataclass
class RiskConfig:
    """全局防爆参数"""
    
    # 账户级防爆
    max_leverage: int = 20                      # Binance 最大杠杆 (交易所限制)
    max_daily_loss_pct: float = 10.0            # 日最大亏损 → 触发停止新开仓
    
    # 品种限制
    blacklist: list = None
    
    def __post_init__(self):
        if self.blacklist is None:
            self.blacklist = []


# ============================================================
# 审批结果 (Pipeline 接口)
# ============================================================

@dataclass
class RiskVerdict:
    """风控审批结果"""
    approved: bool
    reason: str = ""
    warnings: list = None
    adjusted_target: Optional[PortfolioTarget] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# ============================================================
# 兼容旧接口 (check_all 使用)
# ============================================================

@dataclass
class RiskCheckResult:
    """单项风控检查结果"""
    passed: bool
    reason: str = ""
    rule: str = ""

    def __str__(self):
        symbol = "✅" if self.passed else "🚫"
        return f"{symbol} [{self.rule}] {self.reason}"


# ============================================================
# RiskModel — 极简防爆
# ============================================================

class RiskModel:
    """
    全局防爆层 — 只做账户级底线拦截
    
    不干涉策略的:
    - 止损/止盈点位 (策略自决)
    - 仓位比例 (由 Portfolio 层计算)
    - 盈亏比 (策略自决)
    - 交易频率 (策略自决)
    - 持仓数量 (策略自决)
    """
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self._config = config or RiskConfig()
        self._daily_pnl: Dict[int, Decimal] = {}
        self._daily_reset_date: Optional[date] = None
        self._circuit_breaker: bool = False
        self._risk_bypass: bool = False
    
    @property
    def config(self) -> RiskConfig:
        return self._config
    
    @property
    def risk_bypass(self) -> bool:
        """风控是否已关闭 (旁路模式)"""
        return self._risk_bypass
    
    def set_risk_bypass(self, enabled: bool) -> None:
        """开启/关闭风控旁路"""
        self._risk_bypass = enabled
        if enabled:
            logger.warning("[RiskModel] ⚠️ 风控已关闭 — 所有交易将跳过系统风控检查")
        else:
            logger.info("[RiskModel] ✅ 风控已恢复")
    
    # ==============================================================
    # Pipeline 接口: approve_target()
    # ==============================================================
    
    async def approve_target(
        self,
        target: PortfolioTarget,
        available_balance: Decimal,
        total_equity: Decimal,
        open_positions: list,
        user_id: int = 0,
    ) -> RiskVerdict:
        """
        审批 PortfolioTarget — 账户级底线拦截
        
        只检查:
        1. 紧急熔断 (永远生效)
        2. 黑名单
        3. 杠杆上限 (交易所级)
        4. 保证金可用率 (下单余额够不够)
        5. 极端回撤熔断 (日亏损阈值)
        """
        warnings = []
        
        # — 紧急熔断 (永远生效, 不受旁路影响) —
        if self._circuit_breaker:
            return RiskVerdict(
                approved=False,
                reason="🚨 风控熔断中, 禁止一切交易"
            )
        
        # — 风控旁路: 跳过所有检查 —
        if self._risk_bypass:
            logger.info(f"[RiskModel] ⚡ 风控已关闭, 直接放行: {target.summary()}")
            return RiskVerdict(approved=True, warnings=["⚠️ 系统风控已关闭"])
        
        # — 黑名单 —
        if target.symbol in self._config.blacklist:
            return RiskVerdict(
                approved=False,
                reason=f"{target.symbol} 在黑名单中"
            )
        
        # — 杠杆上限 (交易所级限制) —
        if target.leverage > self._config.max_leverage:
            return RiskVerdict(
                approved=False,
                reason=(
                    f"杠杆 {target.leverage}x 超过交易所限制 "
                    f"{self._config.max_leverage}x"
                )
            )
        
        # — 保证金可用率 (核心防爆) —
        if available_balance > 0 and target.required_margin > available_balance:
            return RiskVerdict(
                approved=False,
                reason=(
                    f"保证金不足: 需要 {target.required_margin:.2f}, "
                    f"可用余额 {available_balance:.2f}"
                )
            )
        
        # — 极端回撤熔断 (日亏损阈值) —
        self._reset_daily_if_needed()
        daily_loss = self._daily_pnl.get(user_id, Decimal("0"))
        if total_equity > 0 and daily_loss < 0:
            loss_pct = float(abs(daily_loss) / total_equity * 100)
            if loss_pct >= self._config.max_daily_loss_pct:
                return RiskVerdict(
                    approved=False,
                    reason=(
                        f"日亏损 {loss_pct:.1f}% 已达限制 "
                        f"{self._config.max_daily_loss_pct}%, 停止新开仓"
                    )
                )
            if loss_pct >= self._config.max_daily_loss_pct * 0.8:
                warnings.append(
                    f"⚠️ 日亏损已达 {loss_pct:.1f}%, 接近限制"
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
    
    # ==============================================================
    # 日 PnL 跟踪
    # ==============================================================
    
    def update_daily_pnl(self, user_id: int, realized_pnl: Decimal) -> None:
        """更新用户当日 PnL"""
        self._reset_daily_if_needed()
        current = self._daily_pnl.get(user_id, Decimal("0"))
        self._daily_pnl[user_id] = current + realized_pnl
    
    # ==============================================================
    # 紧急熔断
    # ==============================================================
    
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
    
    # ==============================================================
    # 内部方法
    # ==============================================================
    
    def _reset_daily_if_needed(self) -> None:
        """跨日重置"""
        today = date.today()
        if self._daily_reset_date != today:
            self._daily_pnl.clear()
            self._daily_reset_date = today
