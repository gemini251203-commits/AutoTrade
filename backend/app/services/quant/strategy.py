"""
Strategy Engine - YAML 策略解析 + 条件评估引擎
===============================================
将 YAML 策略配置转化为交易信号

流程:
1. 解析 YAML 策略文件
2. 递归评估 AND/OR 条件组
3. 生成候选信号 (entry / exit)
4. 传递给 AI 审核员做增强判断

支持的比较运算:
- >, <, >=, <=, ==, !=
- crosses_above (上穿), crosses_below (下穿)

YAML 格式参考 implementation_plan.md
"""

import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from loguru import logger

from .indicators import get_indicator, get_indicator_at, INDICATOR_REGISTRY
from app.core.time_utils import utc_now


# ============================================================
# 数据模型
# ============================================================

class SignalType(str, Enum):
    """信号类型"""
    ENTRY = "entry"   # 开仓信号
    EXIT = "exit"     # 平仓信号
    NONE = "none"     # 无信号


class SignalSide(str, Enum):
    """交易方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class ConditionResult:
    """单个条件的评估结果"""
    indicator: str
    compare: str
    target_value: Any
    actual_value: Any
    passed: bool
    description: str = ""

    def __str__(self):
        symbol = "✅" if self.passed else "❌"
        return f"{symbol} {self.indicator} {self.compare} {self.target_value} (actual={self.actual_value})"


@dataclass
class Signal:
    """策略评估产生的信号"""
    signal_type: SignalType
    side: Optional[SignalSide] = None
    strategy_name: str = ""
    symbol: str = ""
    interval: str = ""
    confidence: float = 0.0
    conditions_met: List[ConditionResult] = field(default_factory=list)
    conditions_failed: List[ConditionResult] = field(default_factory=list)
    risk_config: Dict[str, Any] = field(default_factory=dict)
    ai_prompt: str = ""
    
    @property
    def has_signal(self) -> bool:
        return self.signal_type != SignalType.NONE

    def summary(self) -> str:
        """可读的信号摘要"""
        if not self.has_signal:
            return f"[{self.strategy_name}] 无信号"
        met = len(self.conditions_met)
        total = met + len(self.conditions_failed)
        return (
            f"[{self.strategy_name}] {self.signal_type.value.upper()} "
            f"{self.side.value if self.side else '?'} "
            f"({met}/{total} conditions met)"
        )


# ============================================================
# 比较运算符
# ============================================================

def _compare_gt(actual, target) -> bool:
    if actual is None: return False
    return float(actual) > float(target)

def _compare_lt(actual, target) -> bool:
    if actual is None: return False
    return float(actual) < float(target)

def _compare_gte(actual, target) -> bool:
    if actual is None: return False
    return float(actual) >= float(target)

def _compare_lte(actual, target) -> bool:
    if actual is None: return False
    return float(actual) <= float(target)

def _compare_eq(actual, target) -> bool:
    if actual is None: return False
    # 支持 bool 比较: "==" true/false
    if isinstance(target, bool) or (isinstance(target, str) and target.lower() in ("true", "false")):
        target_bool = target if isinstance(target, bool) else (target.lower() == "true")
        return bool(actual) == target_bool
    return float(actual) == float(target)

def _compare_neq(actual, target) -> bool:
    return not _compare_eq(actual, target)


COMPARATORS = {
    ">": _compare_gt,
    "<": _compare_lt,
    ">=": _compare_gte,
    "<=": _compare_lte,
    "==": _compare_eq,
    "!=": _compare_neq,
}


# ============================================================
# 白名单 — 防止 AI 写出系统不支持的字段
# ============================================================

# 顶层允许字段 (随升级阶段同步扩展)
ALLOWED_TOP_KEYS = {
    "name", "symbol", "interval",
    "entry", "exit", "risk", "ai_prompt",
    "alphas", "portfolio", "execution", # pipeline mode
    # L2+
    "timeframes",
    # L3+
    "stages", "state", "time_filter",
    # L4+
    "scoring",
}

# 条件允许字段
ALLOWED_CONDITION_KEYS = {
    "indicator", "compare", "value", "reference",
    # L2+
    "timeframe", "cross",
    # L3+
    "expression", "consecutive",
    # L4+
    "weight",
}

# risk 允许字段
ALLOWED_RISK_KEYS = {
    "side", "leverage", "position_pct",
    "stop_loss_pct", "take_profit_pct",
    # Pipeline mode
    "type", "params",
    # L2+
    "stop_type", "trailing_pct", "atr_stop_multiplier",
    # L4+
    "volatility_adjust",
}

# entry/exit 块允许字段
ALLOWED_BLOCK_KEYS = {"operator", "conditions"}


# ============================================================
# 策略引擎
# ============================================================

class StrategyEngine:
    """
    YAML 策略解析 + 条件评估引擎
    
    Usage:
        engine = StrategyEngine()
        config = engine.parse_yaml(yaml_string)
        signal = engine.evaluate(config, klines)
    """

    def parse_yaml(self, yaml_content: str) -> Dict[str, Any]:
        """
        解析 YAML 策略配置 (含严格白名单校验)
        
        Returns:
            解析后的策略字典
        
        Raises:
            ValueError: YAML 格式错误、缺少必要字段、或包含未知字段
        """
        try:
            config = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 解析失败: {e}")
        
        if not isinstance(config, dict):
            raise ValueError("YAML 顶层必须是字典")
        
        # 1. 白名单 — 顶层字段
        unknown_top = set(config.keys()) - ALLOWED_TOP_KEYS
        if unknown_top:
            raise ValueError(
                f"策略包含未知的顶层字段: {unknown_top}。"
                f"允许的字段: {sorted(ALLOWED_TOP_KEYS)}"
            )
        
        # 2. 校验必要字段
        required = ["name", "symbol"]
        for key in required:
            if key not in config:
                raise ValueError(f"策略缺少必要字段: {key}")
        
        # 3. 设置默认值
        config.setdefault("interval", "1h")
        is_pipeline = any(k in config for k in ("alphas", "portfolio", "execution"))
        
        if not is_pipeline:
            config.setdefault("entry", {"operator": "AND", "conditions": []})
            config.setdefault("exit", {"operator": "OR", "conditions": []})
            config.setdefault("risk", {})
            config.setdefault("ai_prompt", "")
        
        # 4. 白名单 — risk 字段
        risk = config.get("risk", {})
        if isinstance(risk, dict):
            unknown_risk = set(risk.keys()) - ALLOWED_RISK_KEYS
            if unknown_risk:
                raise ValueError(
                    f"risk 包含未知字段: {unknown_risk}。"
                    f"允许的字段: {sorted(ALLOWED_RISK_KEYS)}"
                )
        
        # 5. 白名单 — entry/exit 块字段
        blocks_to_check = [config.get("entry", {}), config.get("exit", {})]
        alphas = config.get("alphas", [])
        if isinstance(alphas, list):
            for alpha in alphas:
                if isinstance(alpha, dict):
                    blocks_to_check.append(alpha.get("entry", {}))
                    blocks_to_check.append(alpha.get("exit", {}))
                    
        for block in blocks_to_check:
            if isinstance(block, dict) and block:
                unknown_block = set(block.keys()) - ALLOWED_BLOCK_KEYS
                if unknown_block:
                    raise ValueError(
                        f"条件块包含未知字段: {unknown_block}。"
                        f"允许的字段: {sorted(ALLOWED_BLOCK_KEYS)}"
                    )
        
        # 6. 校验条件中的指标名称 + 白名单字段
        for block in blocks_to_check:
            self._validate_conditions(block)
        
        # 7. 收集需要的时间框架 (用于多时间框架功能)
        required_tfs = set()
        required_tfs.add(config.get("interval", "1h"))
        for block in blocks_to_check:
            if isinstance(block, dict):
                for cond in block.get("conditions", []):
                    if "timeframe" in cond:
                        required_tfs.add(cond["timeframe"])
        config["_required_timeframes"] = sorted(required_tfs)
        
        return config

    def _validate_conditions(self, block: Dict):
        """校验条件块中的指标名称、比较运算符和字段白名单"""
        if not block or "conditions" not in block:
            return
        
        for cond in block["conditions"]:
            # 白名单 — 条件字段
            unknown_cond = set(cond.keys()) - ALLOWED_CONDITION_KEYS
            if unknown_cond:
                raise ValueError(
                    f"条件包含未知字段: {unknown_cond}。"
                    f"允许的字段: {sorted(ALLOWED_CONDITION_KEYS)}"
                )
            
            # expression 类型条件 — 跳过 indicator 校验
            if "expression" in cond:
                if "compare" not in cond:
                    raise ValueError("expression 条件必须包含 compare 字段")
                compare = cond["compare"]
                if compare not in COMPARATORS:
                    raise ValueError(
                        f"未知的比较运算符: '{compare}'。"
                        f"可用: {list(COMPARATORS.keys())}"
                    )
                continue
            
            indicator = cond.get("indicator", "")
            compare = cond.get("compare", "")
            
            # 检查 reference 类型条件 (indicator vs indicator)
            if "reference" in cond:
                ref = cond["reference"]
                if ref not in INDICATOR_REGISTRY:
                    raise ValueError(
                        f"未知的引用指标: '{ref}'。"
                        f"可用指标: {sorted(INDICATOR_REGISTRY.keys())}"
                    )
            
            if indicator not in INDICATOR_REGISTRY:
                raise ValueError(
                    f"未知的指标: '{indicator}'。"
                    f"可用指标: {sorted(INDICATOR_REGISTRY.keys())}"
                )
            
            # cross 条件使用 cross 字段，不需要 compare
            if "cross" in cond:
                cross_val = cond["cross"]
                if cross_val not in ("above", "below"):
                    raise ValueError(
                        f"cross 值必须是 'above' 或 'below'，当前: '{cross_val}'"
                    )
                continue
            
            if compare and compare not in COMPARATORS:
                raise ValueError(
                    f"未知的比较运算符: '{compare}'。"
                    f"可用: {list(COMPARATORS.keys())}"
                )

    def evaluate(
        self,
        config: Dict[str, Any],
        klines: Any = None,
        klines_map: Optional[Dict[str, list]] = None,
    ) -> Signal:
        """
        评估策略，生成候选信号
        
        Args:
            config: parse_yaml() 返回的策略配置
            klines: 单时间框架 K 线数据 (向后兼容)
            klines_map: 多时间框架 K 线数据 {"1h": [...], "4h": [...]}
        
        Returns:
            Signal 对象
        """
        # 构建 klines_map
        default_interval = config.get("interval", "1h")
        if klines_map is None:
            if klines is None or not klines:
                logger.warning(f"[Strategy] No klines for {config.get('name')}")
                return Signal(signal_type=SignalType.NONE, strategy_name=config.get("name", ""))
            klines_map = {default_interval: klines}
        
        # 时间过滤
        time_filter = config.get("time_filter")
        if time_filter and not self._check_time_filter(time_filter):
            return Signal(
                signal_type=SignalType.NONE,
                strategy_name=config.get("name", ""),
                symbol=config.get("symbol", ""),
                interval=default_interval,
            )

        risk_config = config.get("risk", {})
        side = SignalSide(risk_config.get("side", "buy"))
        ai_prompt = config.get("ai_prompt", "")
        scoring = config.get("scoring", {})

        # 评估开仓条件
        entry_block = config.get("entry", {})
        entry_results = self._evaluate_conditions(entry_block, klines_map, default_interval)
        entry_passed = self._aggregate_results(entry_block, entry_results, scoring)

        # 评估平仓条件
        exit_block = config.get("exit", {})
        exit_results = self._evaluate_conditions(exit_block, klines_map, default_interval)
        exit_passed = self._aggregate_results(exit_block, exit_results, scoring)

        # 生成信号
        met = [r for r in entry_results if r.passed]
        failed = [r for r in entry_results if not r.passed]

        # 计算 confidence (支持权重模式)
        def _calc_confidence(results, block, scoring_config):
            if not results:
                return 0.0
            if scoring_config.get("min_score"):
                total_weight = sum(getattr(r, '_weight', 1) for r in results)
                passed_weight = sum(getattr(r, '_weight', 1) for r in results if r.passed)
                return passed_weight / max(total_weight, 1)
            return len([r for r in results if r.passed]) / max(len(results), 1)

        if exit_passed:
            exit_met = [r for r in exit_results if r.passed]
            exit_failed = [r for r in exit_results if not r.passed]
            return Signal(
                signal_type=SignalType.EXIT,
                side=side,
                strategy_name=config.get("name", ""),
                symbol=config.get("symbol", ""),
                interval=default_interval,
                confidence=_calc_confidence(exit_results, exit_block, scoring),
                conditions_met=exit_met,
                conditions_failed=exit_failed,
                risk_config=risk_config,
                ai_prompt=ai_prompt,
            )
        
        if entry_passed:
            return Signal(
                signal_type=SignalType.ENTRY,
                side=side,
                strategy_name=config.get("name", ""),
                symbol=config.get("symbol", ""),
                interval=default_interval,
                confidence=_calc_confidence(entry_results, entry_block, scoring),
                conditions_met=met,
                conditions_failed=failed,
                risk_config=risk_config,
                ai_prompt=ai_prompt,
            )

        return Signal(
            signal_type=SignalType.NONE,
            strategy_name=config.get("name", ""),
            symbol=config.get("symbol", ""),
            interval=default_interval,
            conditions_met=met,
            conditions_failed=failed,
        )

    def _evaluate_conditions(
        self,
        block: Dict,
        klines_map: Dict[str, list],
        default_interval: str,
    ) -> List[ConditionResult]:
        """评估一个条件块中的所有条件"""
        results = []
        
        if not block or "conditions" not in block:
            return results
        
        for cond in block["conditions"]:
            result = self._evaluate_single(cond, klines_map, default_interval)
            results.append(result)
        
        return results

    def _evaluate_single(
        self,
        cond: Dict,
        klines_map: Dict[str, list],
        default_interval: str,
    ) -> ConditionResult:
        """评估单个条件 (支持 L2-L4 扩展)"""
        # 确定使用哪个时间框架的 K 线
        tf = cond.get("timeframe", default_interval)
        klines = klines_map.get(tf, klines_map.get(default_interval, []))
        
        if not klines:
            return ConditionResult(
                indicator=cond.get("indicator", cond.get("expression", "?")),
                compare=cond.get("compare", cond.get("cross", "?")),
                target_value=cond.get("value"),
                actual_value=None,
                passed=False,
                description=f"无 {tf} K线数据",
            )
        
        # L3: 表达式条件
        if "expression" in cond:
            return self._evaluate_expression(cond, klines)
        
        indicator_name = cond.get("indicator", "")
        weight = cond.get("weight", 1)
        
        # L2: 时序穿越条件
        if "cross" in cond:
            return self._evaluate_cross(cond, klines, indicator_name, weight)
        
        # 普通比较条件
        compare = cond.get("compare", "")
        actual_value = get_indicator(indicator_name, klines)
        
        # 确定目标值
        if "reference" in cond:
            target_value = get_indicator(cond["reference"], klines)
            target_display = cond["reference"]
        else:
            target_value = cond.get("value")
            target_display = target_value
        
        # 执行比较
        if actual_value is None or target_value is None:
            passed = False
        else:
            comparator = COMPARATORS.get(compare)
            passed = comparator(actual_value, target_value) if comparator else False
        
        tf_label = f"[{tf}]" if tf != default_interval else ""
        result = ConditionResult(
            indicator=indicator_name,
            compare=compare,
            target_value=target_display,
            actual_value=actual_value,
            passed=passed,
            description=f"{tf_label}{indicator_name} {compare} {target_display}".strip(),
        )
        result._weight = weight  # type: ignore
        return result
    
    def _evaluate_cross(
        self,
        cond: Dict,
        klines: list,
        indicator_name: str,
        weight: int,
    ) -> ConditionResult:
        """评估时序穿越条件: cross above/below"""
        cross_dir = cond["cross"]  # "above" or "below"
        
        current = get_indicator_at(indicator_name, klines, offset=0)
        previous = get_indicator_at(indicator_name, klines, offset=-1)
        
        # 确定目标值
        if "reference" in cond:
            target_current = get_indicator_at(cond["reference"], klines, offset=0)
            target_previous = get_indicator_at(cond["reference"], klines, offset=-1)
            target_display = cond["reference"]
        else:
            target_current = cond.get("value")
            target_previous = cond.get("value")
            target_display = target_current
        
        if any(v is None for v in [current, previous, target_current, target_previous]):
            passed = False
        elif cross_dir == "above":
            passed = previous < target_previous and current >= target_current
        elif cross_dir == "below":
            passed = previous > target_previous and current <= target_current
        else:
            passed = False
        
        result = ConditionResult(
            indicator=indicator_name,
            compare=f"cross_{cross_dir}",
            target_value=target_display,
            actual_value=current,
            passed=passed,
            description=f"{indicator_name} cross {cross_dir} {target_display}",
        )
        result._weight = weight  # type: ignore
        return result
    
    def _evaluate_expression(
        self,
        cond: Dict,
        klines: list,
    ) -> ConditionResult:
        """评估自定义表达式条件"""
        expr = cond["expression"]
        compare = cond.get("compare", "")
        target_value = cond.get("value")
        weight = cond.get("weight", 1)
        
        try:
            actual_value = self._safe_eval_expression(expr, klines)
        except Exception as e:
            logger.warning(f"[Strategy] Expression eval error: {expr} → {e}")
            actual_value = None
        
        if actual_value is None or target_value is None:
            passed = False
        else:
            comparator = COMPARATORS.get(compare)
            passed = comparator(actual_value, target_value) if comparator else False
        
        result = ConditionResult(
            indicator=expr,
            compare=compare,
            target_value=target_value,
            actual_value=actual_value,
            passed=passed,
            description=f"{expr} {compare} {target_value}",
        )
        result._weight = weight  # type: ignore
        return result
    
    def _safe_eval_expression(self, expr: str, klines: list) -> Optional[float]:
        """
        安全评估数学表达式
        
        只允许: 指标名、数字、+ - * / ( )
        不使用 eval()，通过 AST 白名单实现安全
        """
        import ast
        
        # 替换指标名为实际值
        resolved_expr = expr
        for name in sorted(INDICATOR_REGISTRY.keys(), key=len, reverse=True):
            if name in resolved_expr:
                val = get_indicator(name, klines)
                if val is None:
                    return None
                resolved_expr = resolved_expr.replace(name, str(float(val)))
        
        # AST 安全解析
        try:
            tree = ast.parse(resolved_expr, mode='eval')
        except SyntaxError:
            raise ValueError(f"表达式语法错误: {expr}")
        
        # 只允许安全节点
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Num,
                   ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)
        for node in ast.walk(tree):
            if not isinstance(node, allowed):
                raise ValueError(f"表达式包含不安全操作: {type(node).__name__}")
        
        return float(eval(compile(tree, '<expr>', 'eval')))

    def _aggregate_results(
        self,
        block: Dict,
        results: List[ConditionResult],
        scoring: Optional[Dict] = None,
    ) -> bool:
        """
        聚合条件结果
        
        AND: 所有条件都通过
        OR: 任一条件通过
        SCORE: 权重之和 >= min_score (L4)
        """
        if not results:
            return False
        
        # L4: 评分模式
        if scoring and scoring.get("min_score"):
            min_score = scoring["min_score"]
            total_score = sum(
                getattr(r, '_weight', 1) for r in results if r.passed
            )
            return total_score >= min_score
        
        operator = block.get("operator", "AND").upper()
        passed_list = [r.passed for r in results]
        
        if operator == "AND":
            return all(passed_list)
        elif operator == "OR":
            return any(passed_list)
        else:
            logger.warning(f"[Strategy] Unknown operator: {operator}, defaulting to AND")
            return all(passed_list)
    
    @staticmethod
    def _check_time_filter(time_filter: Dict) -> bool:
        """检查当前时间是否在交易时段内"""
        from datetime import datetime, timezone
        
        now = utc_now()
        
        # 跳过周末
        if time_filter.get("skip_weekends") and now.weekday() >= 5:
            logger.info("[Strategy] 时间过滤: 跳过周末")
            return False
        
        # 跳过特定日期
        skip_dates = time_filter.get("skip_dates", [])
        if now.strftime("%Y-%m-%d") in skip_dates:
            logger.info(f"[Strategy] 时间过滤: 跳过日期 {now.strftime('%Y-%m-%d')}")
            return False
        
        # 交易时段
        trading_hours = time_filter.get("trading_hours", [])
        if not trading_hours:
            return True
        
        current_time = now.strftime("%H:%M")
        for period in trading_hours:
            parts = period.split("-")
            if len(parts) != 2:
                continue
            start, end = parts[0].strip(), parts[1].strip()
            if start <= end:
                if start <= current_time <= end:
                    return True
            else:
                # 跨午夜: 20:00-02:00
                if current_time >= start or current_time <= end:
                    return True
        
        logger.info(f"[Strategy] 时间过滤: 当前 {current_time} 不在交易时段")
        return False


# ============================================================
# 预设策略模板 (Pipeline 式)
# ============================================================

STRATEGY_TEMPLATES = {
    "rsi_fixed": """
name: "RSI 超卖 · 固定仓位"
symbol: BTCUSDT
interval: 1h
alphas:
  - type: "yaml_condition"
    name: "RSI超卖反弹"
    entry:
      operator: AND
      conditions:
        - indicator: rsi
          compare: "<"
          value: 30
        - indicator: volume_ratio
          compare: ">"
          value: 1.2
    exit:
      operator: OR
      conditions:
        - indicator: rsi
          compare: ">"
          value: 70
portfolio:
  type: "fixed_percent"
  params:
    risk_percent: 10
    default_leverage: 3
    default_sl_pct: 3
    default_tp_pct: 9
risk:
  type: "standard"
  params:
    max_leverage: 5
    max_daily_loss_pct: 8
execution:
  type: "market"
""",

    "macd_kelly": """
name: "MACD 金叉 · 凯利仓位"
symbol: BTCUSDT
interval: 1h
alphas:
  - type: "yaml_condition"
    name: "MACD金叉"
    entry:
      operator: AND
      conditions:
        - indicator: macd_golden_cross
          compare: "=="
          value: true
        - indicator: rsi
          compare: ">"
          value: 40
    exit:
      operator: OR
      conditions:
        - indicator: macd_death_cross
          compare: "=="
          value: true
portfolio:
  type: "kelly"
  params:
    kelly_fraction: 0.5
    max_risk_percent: 20
    default_leverage: 5
    odds_ratio: 2.5
risk:
  type: "standard"
  params:
    max_leverage: 10
    max_daily_loss_pct: 12
execution:
  type: "market"
""",

    "ai_conservative": """
name: "AI 研判 · 保守风控"
symbol: BTCUSDT
interval: 1h
alphas:
  - type: "ai_agent"
    name: "AI智能研判"
    confidence_threshold: 0.6
portfolio:
  type: "fixed_percent"
  params:
    risk_percent: 8
    default_leverage: 2
    default_sl_pct: 2
    default_tp_pct: 6
risk:
  type: "standard"
  params:
    max_leverage: 3
    max_daily_loss_pct: 5
    max_daily_trades: 10
execution:
  type: "market"
""",
}


def get_template(name: str) -> Optional[str]:
    """获取预设策略模板 YAML"""
    return STRATEGY_TEMPLATES.get(name)


def list_templates() -> List[Dict[str, str]]:
    """列出所有可用模板 (含模块组合信息)"""
    import yaml as _yaml

    result = []
    for key, yaml_content in STRATEGY_TEMPLATES.items():
        config = _yaml.safe_load(yaml_content.strip())
        if not config:
            continue

        # 提取模块组合描述
        alphas = config.get("alphas", [])
        alpha_names = [a.get("name", a.get("type", "?")) for a in alphas if isinstance(a, dict)]
        portfolio_type = config.get("portfolio", {}).get("type", "?")
        risk_type = config.get("risk", {}).get("type", "?")

        result.append({
            "id": key,
            "name": config.get("name", key),
            "symbol": config.get("symbol", "BTCUSDT"),
            "interval": config.get("interval", "1h"),
            "strategy_type": "pipeline",
            "modules": f"{' + '.join(alpha_names)} → {portfolio_type} → {risk_type}",
        })
    return result

