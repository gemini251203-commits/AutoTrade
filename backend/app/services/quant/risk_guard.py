"""
Risk Guard - 风控保底层
========================
硬性限制 — AI 也不能绕过

风控检查清单:
1. 单笔仓位不超过总资金的 N%
2. 总敞口不超过 N%
3. 单日最大亏损限制
4. 单日交易次数上限
5. 同一交易对最大持仓数
6. 杠杆限制
7. 最小盈亏比检查
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from loguru import logger


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    passed: bool
    reason: str = ""
    rule: str = ""

    def __str__(self):
        symbol = "✅" if self.passed else "🚫"
        return f"{symbol} [{self.rule}] {self.reason}"


class RiskGuard:
    """
    风控守卫 — 最后防线
    
    所有硬限制在此定义，策略和 AI 都不能绕过
    """

    # ==================== 系统级硬限制 ====================
    # 这些值是绝对上限，Autopilot 自动交易不能超过这些
    # 2026-02-18: 全面收紧 (第 #9 笔交易 -2318u 教训)

    # 单笔仓位上限 (占总资金的百分比)
    MAX_POSITION_PCT = 30.0

    # 总敞口上限 (所有仓位占总资金的百分比)  
    MAX_TOTAL_EXPOSURE_PCT = 100.0

    # 单日最大亏损 (占总资金的百分比) — 触发则当日停机
    MAX_DAILY_LOSS_PCT = 10.0

    # 单日最大交易次数
    MAX_DAILY_TRADES = 20

    # 同一交易对最大同时持仓数
    MAX_SAME_SYMBOL_POSITIONS = 3

    # 最大允许杠杆
    MAX_LEVERAGE = 20

    # 最小盈亏比 (take_profit / stop_loss)
    MIN_RISK_REWARD_RATIO = 1.0

    # 最小交易金额 (USDT)
    MIN_TRADE_AMOUNT = 5.0

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
        执行所有风控检查
        
        Args:
            signal_side: "buy" or "sell"
            symbol: 交易对 (如 "BTCUSDT")
            position_pct: 策略请求的仓位百分比
            leverage: 策略请求的杠杆倍数
            stop_loss_pct: 止损百分比
            take_profit_pct: 止盈百分比
            wallet_balance: 当前钱包余额 (USDT)
            open_positions: 当前持仓列表
            today_trades: 今日已交易次数
            today_pnl: 今日已实现盈亏 (USDT)
        
        Returns:
            (通过: bool, 检查详情: List[RiskCheckResult])
        """
        results: List[RiskCheckResult] = []

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
                f"[RiskGuard] 🚫 信号被拦截: {symbol} {signal_side} | "
                f"失败规则: {[r.rule for r in failed]}"
            )
        else:
            logger.info(f"[RiskGuard] ✅ 信号通过风控: {symbol} {signal_side}")

        return all_passed, results

    def _check_daily_loss(self, today_pnl: float, balance: float) -> RiskCheckResult:
        """检查日亏损限制"""
        if balance <= 0:
            return RiskCheckResult(
                passed=False,
                rule="daily_loss",
                reason="钱包余额为零",
            )
        
        loss_pct = abs(min(today_pnl, 0)) / balance * 100
        
        if loss_pct >= self.MAX_DAILY_LOSS_PCT:
            return RiskCheckResult(
                passed=False,
                rule="daily_loss",
                reason=(
                    f"今日已亏损 {loss_pct:.1f}%, "
                    f"超过限制 {self.MAX_DAILY_LOSS_PCT}%, 当日停机"
                ),
            )
        return RiskCheckResult(
            passed=True,
            rule="daily_loss",
            reason=f"今日盈亏 {loss_pct:.1f}% / {self.MAX_DAILY_LOSS_PCT}% 限制",
        )

    def _check_daily_trades(self, today_trades: int) -> RiskCheckResult:
        """检查日交易次数"""
        if today_trades >= self.MAX_DAILY_TRADES:
            return RiskCheckResult(
                passed=False,
                rule="daily_trades",
                reason=f"今日已交易 {today_trades} 次, 达到上限 {self.MAX_DAILY_TRADES}",
            )
        return RiskCheckResult(
            passed=True,
            rule="daily_trades",
            reason=f"今日 {today_trades}/{self.MAX_DAILY_TRADES} 笔",
        )

    def _check_position_size(self, position_pct: float, balance: float) -> RiskCheckResult:
        """检查单笔仓位大小"""
        effective_pct = min(position_pct, self.MAX_POSITION_PCT)
        
        if position_pct > self.MAX_POSITION_PCT:
            return RiskCheckResult(
                passed=False,
                rule="position_size",
                reason=(
                    f"策略请求 {position_pct}% 仓位, "
                    f"超过系统上限 {self.MAX_POSITION_PCT}%"
                ),
            )
        
        trade_amount = balance * position_pct / 100
        return RiskCheckResult(
            passed=True,
            rule="position_size",
            reason=f"{position_pct}% = ${trade_amount:.2f}",
        )

    def _check_total_exposure(
        self,
        new_position_pct: float,
        balance: float,
        open_positions: List[Dict],
    ) -> RiskCheckResult:
        """检查总敞口"""
        # 计算现有敞口
        existing_exposure = sum(
            abs(float(p.get("notional", 0))) for p in open_positions
        )
        existing_pct = (existing_exposure / balance * 100) if balance > 0 else 0
        
        total_pct = existing_pct + new_position_pct
        
        if total_pct > self.MAX_TOTAL_EXPOSURE_PCT:
            return RiskCheckResult(
                passed=False,
                rule="total_exposure",
                reason=(
                    f"现有敞口 {existing_pct:.1f}% + 新仓 {new_position_pct}% = "
                    f"{total_pct:.1f}%, 超过上限 {self.MAX_TOTAL_EXPOSURE_PCT}%"
                ),
            )
        return RiskCheckResult(
            passed=True,
            rule="total_exposure",
            reason=f"总敞口 {total_pct:.1f}% / {self.MAX_TOTAL_EXPOSURE_PCT}%",
        )

    def _check_same_symbol(
        self,
        symbol: str,
        open_positions: List[Dict],
    ) -> RiskCheckResult:
        """检查同交易对持仓数"""
        same_symbol_count = sum(
            1 for p in open_positions
            if p.get("symbol", "").upper() == symbol.upper()
        )
        
        if same_symbol_count >= self.MAX_SAME_SYMBOL_POSITIONS:
            return RiskCheckResult(
                passed=False,
                rule="same_symbol",
                reason=(
                    f"{symbol} 已有 {same_symbol_count} 个持仓, "
                    f"达到上限 {self.MAX_SAME_SYMBOL_POSITIONS}"
                ),
            )
        return RiskCheckResult(
            passed=True,
            rule="same_symbol",
            reason=f"{symbol} 持仓 {same_symbol_count}/{self.MAX_SAME_SYMBOL_POSITIONS}",
        )

    def _check_leverage(self, leverage: int) -> RiskCheckResult:
        """检查杠杆"""
        if leverage > self.MAX_LEVERAGE:
            return RiskCheckResult(
                passed=False,
                rule="leverage",
                reason=f"杠杆 {leverage}x 超过系统上限 {self.MAX_LEVERAGE}x",
            )
        return RiskCheckResult(
            passed=True,
            rule="leverage",
            reason=f"杠杆 {leverage}x / {self.MAX_LEVERAGE}x",
        )

    def _check_risk_reward(
        self,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> RiskCheckResult:
        """检查盈亏比"""
        if stop_loss_pct <= 0:
            return RiskCheckResult(
                passed=False,
                rule="risk_reward",
                reason="止损未设置 (stop_loss_pct = 0)",
            )
        
        ratio = take_profit_pct / stop_loss_pct
        
        if ratio < self.MIN_RISK_REWARD_RATIO:
            return RiskCheckResult(
                passed=False,
                rule="risk_reward",
                reason=(
                    f"盈亏比 {ratio:.1f}:1 (TP={take_profit_pct}% / SL={stop_loss_pct}%), "
                    f"低于最小要求 {self.MIN_RISK_REWARD_RATIO}:1"
                ),
            )
        return RiskCheckResult(
            passed=True,
            rule="risk_reward",
            reason=f"盈亏比 {ratio:.1f}:1",
        )

    def _check_min_amount(self, trade_amount: float) -> RiskCheckResult:
        """检查最小交易金额"""
        if trade_amount < self.MIN_TRADE_AMOUNT:
            return RiskCheckResult(
                passed=False,
                rule="min_amount",
                reason=f"交易金额 ${trade_amount:.2f} 低于最小 ${self.MIN_TRADE_AMOUNT}",
            )
        return RiskCheckResult(
            passed=True,
            rule="min_amount",
            reason=f"交易金额 ${trade_amount:.2f}",
        )

    def clamp_params(self, risk_config: Dict) -> Dict:
        """
        将策略的风控参数钳制在系统限制内
        
        如果策略请求超限, 自动降级而不是拒绝
        """
        clamped = dict(risk_config)
        
        if clamped.get("leverage", 1) > self.MAX_LEVERAGE:
            logger.warning(
                f"[RiskGuard] 杠杆 {clamped['leverage']}x → {self.MAX_LEVERAGE}x (钳制)"
            )
            clamped["leverage"] = self.MAX_LEVERAGE
        
        if clamped.get("position_pct", 0) > self.MAX_POSITION_PCT:
            logger.warning(
                f"[RiskGuard] 仓位 {clamped['position_pct']}% → {self.MAX_POSITION_PCT}% (钳制)"
            )
            clamped["position_pct"] = self.MAX_POSITION_PCT
        
        return clamped


# 全局单例
risk_guard = RiskGuard()
