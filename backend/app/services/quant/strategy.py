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

from .indicators import get_indicator, INDICATOR_REGISTRY


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
        解析 YAML 策略配置
        
        Returns:
            解析后的策略字典
        
        Raises:
            ValueError: YAML 格式错误或缺少必要字段
        """
        try:
            config = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 解析失败: {e}")
        
        # 校验必要字段
        required = ["name", "symbol"]
        for key in required:
            if key not in config:
                raise ValueError(f"策略缺少必要字段: {key}")
        
        # 设置默认值
        config.setdefault("interval", "1h")
        config.setdefault("entry", {"operator": "AND", "conditions": []})
        config.setdefault("exit", {"operator": "OR", "conditions": []})
        config.setdefault("risk", {})
        config.setdefault("ai_prompt", "")
        
        # 校验条件中的指标名称
        self._validate_conditions(config.get("entry", {}))
        self._validate_conditions(config.get("exit", {}))
        
        return config

    def _validate_conditions(self, block: Dict):
        """校验条件块中的指标名称和比较运算符"""
        if not block or "conditions" not in block:
            return
        
        for cond in block["conditions"]:
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
            
            if compare not in COMPARATORS:
                raise ValueError(
                    f"未知的比较运算符: '{compare}'。"
                    f"可用: {list(COMPARATORS.keys())}"
                )

    def evaluate(
        self,
        config: Dict[str, Any],
        klines: List[Dict],
    ) -> Signal:
        """
        评估策略，生成候选信号
        
        Args:
            config: parse_yaml() 返回的策略配置
            klines: K 线数据
        
        Returns:
            Signal 对象
        """
        if not klines:
            logger.warning(f"[Strategy] No klines for {config.get('name')}")
            return Signal(signal_type=SignalType.NONE, strategy_name=config.get("name", ""))

        risk_config = config.get("risk", {})
        side = SignalSide(risk_config.get("side", "buy"))
        ai_prompt = config.get("ai_prompt", "")

        # 评估开仓条件
        entry_block = config.get("entry", {})
        entry_results = self._evaluate_conditions(entry_block, klines)
        entry_passed = self._aggregate_results(entry_block, entry_results)

        # 评估平仓条件
        exit_block = config.get("exit", {})
        exit_results = self._evaluate_conditions(exit_block, klines)
        exit_passed = self._aggregate_results(exit_block, exit_results)

        # 生成信号
        met = [r for r in entry_results if r.passed]
        failed = [r for r in entry_results if not r.passed]

        if exit_passed:
            exit_met = [r for r in exit_results if r.passed]
            exit_failed = [r for r in exit_results if not r.passed]
            return Signal(
                signal_type=SignalType.EXIT,
                side=side,
                strategy_name=config.get("name", ""),
                symbol=config.get("symbol", ""),
                interval=config.get("interval", "1h"),
                confidence=len(exit_met) / max(len(exit_results), 1),
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
                interval=config.get("interval", "1h"),
                confidence=len(met) / max(len(entry_results), 1),
                conditions_met=met,
                conditions_failed=failed,
                risk_config=risk_config,
                ai_prompt=ai_prompt,
            )

        return Signal(
            signal_type=SignalType.NONE,
            strategy_name=config.get("name", ""),
            symbol=config.get("symbol", ""),
            interval=config.get("interval", "1h"),
            conditions_met=met,
            conditions_failed=failed,
        )

    def _evaluate_conditions(
        self,
        block: Dict,
        klines: List[Dict],
    ) -> List[ConditionResult]:
        """评估一个条件块中的所有条件"""
        results = []
        
        if not block or "conditions" not in block:
            return results
        
        for cond in block["conditions"]:
            result = self._evaluate_single(cond, klines)
            results.append(result)
        
        return results

    def _evaluate_single(
        self,
        cond: Dict,
        klines: List[Dict],
    ) -> ConditionResult:
        """评估单个条件"""
        indicator_name = cond["indicator"]
        compare = cond["compare"]
        
        # 获取当前指标值
        actual_value = get_indicator(indicator_name, klines)
        
        # 确定目标值: 固定值 or 引用另一个指标
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
            if comparator is None:
                passed = False
            else:
                passed = comparator(actual_value, target_value)
        
        return ConditionResult(
            indicator=indicator_name,
            compare=compare,
            target_value=target_display,
            actual_value=actual_value,
            passed=passed,
            description=f"{indicator_name} {compare} {target_display}",
        )

    def _aggregate_results(
        self,
        block: Dict,
        results: List[ConditionResult],
    ) -> bool:
        """
        聚合条件结果
        
        AND: 所有条件都通过
        OR: 任一条件通过
        """
        if not results:
            return False
        
        operator = block.get("operator", "AND").upper()
        passed_list = [r.passed for r in results]
        
        if operator == "AND":
            return all(passed_list)
        elif operator == "OR":
            return any(passed_list)
        else:
            logger.warning(f"[Strategy] Unknown operator: {operator}, defaulting to AND")
            return all(passed_list)


# ============================================================
# 预设策略模板
# ============================================================

STRATEGY_TEMPLATES = {
    "rsi_oversold": """
name: "RSI 超卖反弹"
symbol: BTCUSDT
interval: 1h
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
ai_prompt: |
  策略检测到 RSI 超卖，请额外确认：
  1. 是否有底部反转 K 线形态 (pinbar/锤子/吞没)
  2. 下跌趋势是否已经放缓
  3. 成交量是否配合
risk:
  side: buy
  leverage: 3
  position_pct: 10
  stop_loss_pct: 3
  take_profit_pct: 9
""",

    "macd_golden_cross": """
name: "MACD 金叉"
symbol: BTCUSDT
interval: 1h
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
ai_prompt: |
  MACD刚刚金叉，请检查：
  1. 金叉是否发生在零轴附近或上方（强势金叉更可靠）
  2. 成交量是否在放大
  3. 价格是否站上 EMA20
risk:
  side: buy
  leverage: 2
  position_pct: 8
  stop_loss_pct: 4
  take_profit_pct: 12
""",

    "bollinger_bounce": """
name: "布林带下轨反弹"
symbol: BTCUSDT
interval: 1h
entry:
  operator: AND
  conditions:
    - indicator: close
      compare: "<="
      reference: bollinger_lower
    - indicator: rsi
      compare: "<"
      value: 35
exit:
  operator: OR
  conditions:
    - indicator: close
      compare: ">="
      reference: bollinger_upper
    - indicator: rsi
      compare: ">"
      value: 70
ai_prompt: |
  价格触及布林带下轨，请判断：
  1. 是否只是正常回踩还是趋势性下跌
  2. 布林带宽度是否在收窄（这意味着即将变盘）
  3. 参考历史经验做出判断
risk:
  side: buy
  leverage: 2
  position_pct: 10
  stop_loss_pct: 3
  take_profit_pct: 6
""",

    "ema_trend": """
name: "均线趋势追踪"
symbol: BTCUSDT
interval: 4h
entry:
  operator: AND
  conditions:
    - indicator: golden_cross
      compare: "=="
      value: true
    - indicator: close
      compare: ">"
      reference: ema_50
exit:
  operator: OR
  conditions:
    - indicator: death_cross
      compare: "=="
      value: true
    - indicator: close
      compare: "<"
      reference: ema_50
ai_prompt: |
  均线金叉出现，请确认：
  1. 这是趋势启动还是假突破
  2. 更大周期（日线）趋势方向如何
  3. 当前位置是否追高
risk:
  side: buy
  leverage: 2
  position_pct: 15
  stop_loss_pct: 5
  take_profit_pct: 15
""",

    "pinbar_support": """
name: "Pinbar 支撑位反转"
symbol: BTCUSDT
interval: 1h
entry:
  operator: AND
  conditions:
    - indicator: pinbar_at_support
      compare: "=="
      value: true
    - indicator: rsi
      compare: "<"
      value: 45
exit:
  operator: OR
  conditions:
    - indicator: rsi
      compare: ">"
      value: 70
    - indicator: near_resistance
      compare: "=="
      value: true
ai_prompt: |
  检测到支撑位附近出现 Pinbar，这是高概率反转信号。请确认：
  1. 该支撑位是否被多次验证（强度如何）
  2. Pinbar 的下影线是否足够长
  3. 之后有没有确认 K 线（小阳线跟随）
  4. 历史上类似模式的胜率如何
risk:
  side: buy
  leverage: 3
  position_pct: 12
  stop_loss_pct: 2
  take_profit_pct: 6
""",
}


def get_template(name: str) -> Optional[str]:
    """获取预设策略模板 YAML"""
    return STRATEGY_TEMPLATES.get(name)


def list_templates() -> List[Dict[str, str]]:
    """列出所有可用模板"""
    engine = StrategyEngine()
    result = []
    for key, yaml_content in STRATEGY_TEMPLATES.items():
        config = engine.parse_yaml(yaml_content.strip())
        result.append({
            "id": key,
            "name": config["name"],
            "symbol": config["symbol"],
            "interval": config["interval"],
        })
    return result
