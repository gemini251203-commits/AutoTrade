"""
Risk Model — 统一风控审批层
==============================
合并了原 RiskGuard + LEAN 风格 RiskModel

职责:
1. 预审批 PortfolioTarget (Pipeline 使用)
2. check_all(): 兼容旧式 Autopilot / Agent 调用
3. clamp_params(): 参数钳制 (超限自动降级)
4. 紧急熔断 (一票否决)
5. 日交易次数 / 盈亏比 / 最小金额检查

与 RiskEngine 的关系:
- RiskEngine 保持不变 (计算层: 盈亏、保证金率、强平价)
- RiskModel 是审批层 (决策层: 是否允许交易)
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple

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
    max_same_symbol_positions: int = 3                  # 同品种最大持仓数
    max_daily_loss_pct: float = 10.0                    # 日最大亏损 (占权益%)
    max_total_exposure_pct: float = 200.0               # 最大总敞口 (占权益%)
    max_daily_trades: int = 20                          # 日最大交易次数
    
    # 交易质量
    min_risk_reward_ratio: float = 1.0                  # 最小盈亏比
    min_trade_amount: float = 5.0                       # 最小交易金额 (USDT)
    
    # 品种限制
    blacklist: list = None                              # 禁止交易的品种
    
    def __post_init__(self):
        if self.blacklist is None:
            self.blacklist = []


# ============================================================
# 检查结果 (兼容旧 RiskGuard 接口)
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
# 审批结果 (Pipeline 接口)
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
# RiskModel (统一风控)
# ============================================================

class RiskModel:
    """
    统一风控模型 — 合并了 RiskGuard 的所有检查
    
    两种使用方式:
    1. Pipeline: approve_target(PortfolioTarget) → RiskVerdict
    2. 兼容旧调用: check_all(...) → (bool, List[RiskCheckResult])
    """
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self._config = config or RiskConfig()
        self._daily_pnl: Dict[int, Decimal] = {}           # user_id → 当日 PnL
        self._daily_reset_date: Optional[date] = None
        self._circuit_breaker: bool = False                  # 紧急熔断
        self._risk_bypass: bool = False                      # 风控旁路 (跳过所有检查)
    
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
    # 1. Pipeline 接口: approve_target()
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
    
    # ==============================================================
    # 2. 兼容旧接口: check_all() (替代 RiskGuard.check_all)
    # ==============================================================
    
    def check_all(
        self,
        signal_side: str,
        symbol: str,
        position_pct: float,
        leverage: int,
        stop_loss_pct: float,
        take_profit_pct: float,
        wallet_balance: float,
        open_positions: List[Dict],
        today_trades: int,
        today_pnl: float,
    ) -> Tuple[bool, List[RiskCheckResult]]:
        """
        执行所有风控检查 (兼容 RiskGuard 接口)
        
        Returns:
            (通过: bool, 检查详情: List[RiskCheckResult])
        """
        results: List[RiskCheckResult] = []
        cfg = self._config

        # 0. 熔断
        if self._circuit_breaker:
            results.append(RiskCheckResult(
                passed=False, rule="circuit_breaker",
                reason="🚨 风控熔断中, 禁止一切交易"
            ))
            return False, results

        # 0.5 风控旁路
        if self._risk_bypass:
            results.append(RiskCheckResult(
                passed=True, rule="bypass",
                reason="⚠️ 系统风控已关闭, 由策略自行控制风险"
            ))
            logger.info(f"[RiskModel] ⚡ 风控已关闭, 跳过 check_all: {symbol} {signal_side}")
            return True, results

        # 1. 日亏损限制
        results.append(self._check_daily_loss(today_pnl, wallet_balance))

        # 2. 日交易次数
        results.append(self._check_daily_trades(today_trades))

        # 3. 单笔仓位
        results.append(self._check_position_size(position_pct, wallet_balance))

        # 4. 总敞口
        results.append(self._check_total_exposure(
            position_pct, wallet_balance, open_positions
        ))

        # 5. 同交易对持仓数
        results.append(self._check_same_symbol(symbol, open_positions))

        # 6. 杠杆
        results.append(self._check_leverage(leverage))

        # 7. 盈亏比
        results.append(self._check_risk_reward(stop_loss_pct, take_profit_pct))

        # 8. 最小交易金额
        trade_amount = wallet_balance * position_pct / 100
        results.append(self._check_min_amount(trade_amount))

        # 汇总
        all_passed = all(r.passed for r in results)
        
        if not all_passed:
            failed = [r for r in results if not r.passed]
            logger.warning(
                f"[RiskModel] 🚫 信号被拦截: {symbol} {signal_side} | "
                f"失败规则: {[r.rule for r in failed]}"
            )
        else:
            logger.info(f"[RiskModel] ✅ 信号通过风控: {symbol} {signal_side}")

        return all_passed, results

    # ==============================================================
    # 3. 参数钳制 (替代 RiskGuard.clamp_params)
    # ==============================================================
    
    def clamp_params(self, risk_config: Dict) -> Dict:
        """
        将策略的风控参数钳制在系统限制内
        
        如果策略请求超限, 自动降级而不是拒绝
        """
        clamped = dict(risk_config)
        cfg = self._config
        
        if clamped.get("leverage", 1) > cfg.max_leverage:
            logger.warning(
                f"[RiskModel] 杠杆 {clamped['leverage']}x → {cfg.max_leverage}x (钳制)"
            )
            clamped["leverage"] = cfg.max_leverage
        
        if clamped.get("position_pct", 0) > cfg.max_single_margin_pct:
            logger.warning(
                f"[RiskModel] 仓位 {clamped['position_pct']}% → "
                f"{cfg.max_single_margin_pct}% (钳制)"
            )
            clamped["position_pct"] = cfg.max_single_margin_pct
        
        return clamped

    # ==============================================================
    # 4. 日 PnL 跟踪
    # ==============================================================
    
    def update_daily_pnl(self, user_id: int, realized_pnl: Decimal) -> None:
        """更新用户当日 PnL"""
        self._reset_daily_if_needed()
        current = self._daily_pnl.get(user_id, Decimal("0"))
        self._daily_pnl[user_id] = current + realized_pnl
    
    # ==============================================================
    # 5. 紧急熔断
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
    # 内部检查方法 (check_all 使用)
    # ==============================================================
    
    def _check_daily_loss(self, today_pnl: float, balance: float) -> RiskCheckResult:
        """检查日亏损限制"""
        cfg = self._config
        if balance <= 0:
            return RiskCheckResult(
                passed=False, rule="daily_loss", reason="钱包余额为零",
            )
        
        loss_pct = abs(min(today_pnl, 0)) / balance * 100
        
        if loss_pct >= cfg.max_daily_loss_pct:
            return RiskCheckResult(
                passed=False, rule="daily_loss",
                reason=(
                    f"今日已亏损 {loss_pct:.1f}%, "
                    f"超过限制 {cfg.max_daily_loss_pct}%, 当日停机"
                ),
            )
        return RiskCheckResult(
            passed=True, rule="daily_loss",
            reason=f"今日盈亏 {loss_pct:.1f}% / {cfg.max_daily_loss_pct}% 限制",
        )

    def _check_daily_trades(self, today_trades: int) -> RiskCheckResult:
        """检查日交易次数"""
        cfg = self._config
        if today_trades >= cfg.max_daily_trades:
            return RiskCheckResult(
                passed=False, rule="daily_trades",
                reason=f"今日已交易 {today_trades} 次, 达到上限 {cfg.max_daily_trades}",
            )
        return RiskCheckResult(
            passed=True, rule="daily_trades",
            reason=f"今日 {today_trades}/{cfg.max_daily_trades} 笔",
        )

    def _check_position_size(self, position_pct: float, balance: float) -> RiskCheckResult:
        """检查单笔仓位大小"""
        cfg = self._config
        if position_pct > cfg.max_single_margin_pct:
            return RiskCheckResult(
                passed=False, rule="position_size",
                reason=(
                    f"策略请求 {position_pct}% 仓位, "
                    f"超过系统上限 {cfg.max_single_margin_pct}%"
                ),
            )
        
        trade_amount = balance * position_pct / 100
        return RiskCheckResult(
            passed=True, rule="position_size",
            reason=f"{position_pct}% = ${trade_amount:.2f}",
        )

    def _check_total_exposure(
        self,
        new_position_pct: float,
        balance: float,
        open_positions: List[Dict],
    ) -> RiskCheckResult:
        """检查总敞口"""
        cfg = self._config
        existing_exposure = sum(
            abs(float(p.get("notional", p.get("margin", 0)))) for p in open_positions
        )
        existing_pct = (existing_exposure / balance * 100) if balance > 0 else 0
        
        total_pct = existing_pct + new_position_pct
        
        if total_pct > cfg.max_total_exposure_pct:
            return RiskCheckResult(
                passed=False, rule="total_exposure",
                reason=(
                    f"现有敞口 {existing_pct:.1f}% + 新仓 {new_position_pct}% = "
                    f"{total_pct:.1f}%, 超过上限 {cfg.max_total_exposure_pct}%"
                ),
            )
        return RiskCheckResult(
            passed=True, rule="total_exposure",
            reason=f"总敞口 {total_pct:.1f}% / {cfg.max_total_exposure_pct}%",
        )

    def _check_same_symbol(
        self,
        symbol: str,
        open_positions: List[Dict],
    ) -> RiskCheckResult:
        """检查同交易对持仓数"""
        cfg = self._config
        same_symbol_count = sum(
            1 for p in open_positions
            if p.get("symbol", "").upper() == symbol.upper()
        )
        
        if same_symbol_count >= cfg.max_same_symbol_positions:
            return RiskCheckResult(
                passed=False, rule="same_symbol",
                reason=(
                    f"{symbol} 已有 {same_symbol_count} 个持仓, "
                    f"达到上限 {cfg.max_same_symbol_positions}"
                ),
            )
        return RiskCheckResult(
            passed=True, rule="same_symbol",
            reason=f"{symbol} 持仓 {same_symbol_count}/{cfg.max_same_symbol_positions}",
        )

    def _check_leverage(self, leverage: int) -> RiskCheckResult:
        """检查杠杆"""
        cfg = self._config
        if leverage > cfg.max_leverage:
            return RiskCheckResult(
                passed=False, rule="leverage",
                reason=f"杠杆 {leverage}x 超过系统上限 {cfg.max_leverage}x",
            )
        return RiskCheckResult(
            passed=True, rule="leverage",
            reason=f"杠杆 {leverage}x / {cfg.max_leverage}x",
        )

    def _check_risk_reward(
        self,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> RiskCheckResult:
        """检查盈亏比"""
        cfg = self._config
        if stop_loss_pct <= 0:
            return RiskCheckResult(
                passed=False, rule="risk_reward",
                reason="止损未设置 (stop_loss_pct = 0)",
            )
        
        ratio = take_profit_pct / stop_loss_pct
        
        if ratio < cfg.min_risk_reward_ratio:
            return RiskCheckResult(
                passed=False, rule="risk_reward",
                reason=(
                    f"盈亏比 {ratio:.1f}:1 (TP={take_profit_pct}% / SL={stop_loss_pct}%), "
                    f"低于最小要求 {cfg.min_risk_reward_ratio}:1"
                ),
            )
        return RiskCheckResult(
            passed=True, rule="risk_reward",
            reason=f"盈亏比 {ratio:.1f}:1",
        )

    def _check_min_amount(self, trade_amount: float) -> RiskCheckResult:
        """检查最小交易金额"""
        cfg = self._config
        if trade_amount < cfg.min_trade_amount:
            return RiskCheckResult(
                passed=False, rule="min_amount",
                reason=f"交易金额 ${trade_amount:.2f} 低于最小 ${cfg.min_trade_amount}",
            )
        return RiskCheckResult(
            passed=True, rule="min_amount",
            reason=f"交易金额 ${trade_amount:.2f}",
        )

    def _reset_daily_if_needed(self) -> None:
        """跨日重置"""
        today = date.today()
        if self._daily_reset_date != today:
            self._daily_pnl.clear()
            self._daily_reset_date = today
