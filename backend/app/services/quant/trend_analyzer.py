"""
Trend Analyzer Engine — 趋势分析引擎
=====================================
用 YAML 方案配置分析维度和参数，输出市场体制判断 + 策略建议。

4 个分析维度:
1. trend      — 趋势方向 (uptrend/downtrend/ranging)
2. strength   — 趋势强度 (strong/moderate/weak)
3. volatility — 波动率环境 (high/normal/low)
4. momentum   — 动量状态 (bullish/bearish/neutral)

每个维度支持多种分析方法，每种方法有独立参数。
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from loguru import logger
import yaml

from .indicators import (
    calculate_ema, calculate_ema_series,
    calculate_rsi, calculate_macd, calculate_bollinger,
    calculate_atr, calculate_obv, calculate_volume_ratio,
    calculate_kdj,
)


# ============================================================
# 数据模型
# ============================================================


@dataclass
class TrendResult:
    """趋势分析结果"""
    # 趋势方向
    direction: str = "unknown"       # uptrend / downtrend / ranging
    direction_score: float = 0.0     # -100 (极空) ~ +100 (极多)
    direction_detail: str = ""

    # 趋势强度
    strength: str = "unknown"        # strong / moderate / weak
    strength_score: float = 0.0      # 0 ~ 100
    strength_detail: str = ""

    # 波动率
    volatility: str = "unknown"      # high / normal / low
    volatility_score: float = 0.0    # 0 ~ 100
    volatility_detail: str = ""

    # 动量
    momentum: str = "unknown"        # bullish / bearish / neutral
    momentum_score: float = 0.0      # -100 ~ +100
    momentum_detail: str = ""

    # 综合
    regime: str = "unknown"          # 市场体制: trending_up / trending_down / ranging / volatile
    confidence: float = 0.0          # 0 ~ 100
    suitable_strategies: List[str] = field(default_factory=list)
    unsuitable_strategies: List[str] = field(default_factory=list)

    # 元信息
    scheme_name: str = ""
    symbol: str = ""
    timeframe: str = ""

    def summary(self) -> str:
        """一句话摘要"""
        arrow = {"uptrend": "📈", "downtrend": "📉", "ranging": "↔️"}.get(self.direction, "❓")
        return (
            f"{arrow} {self.symbol} {self.direction}({self.strength}) "
            f"| 波动: {self.volatility} | 动量: {self.momentum} "
            f"| 适合: {', '.join(self.suitable_strategies[:3]) or '无'}"
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# 分析方法注册
# ============================================================


class TrendAnalyzer:
    """
    趋势分析引擎

    Usage:
        analyzer = TrendAnalyzer()
        config = analyzer.parse_yaml(yaml_string)
        result = analyzer.analyze(config, klines)
    """

    def parse_yaml(self, yaml_content: str) -> Dict[str, Any]:
        """解析趋势分析方案 YAML"""
        try:
            config = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 解析失败: {e}")

        if not isinstance(config, dict):
            raise ValueError("方案配置必须是字典格式")

        # 至少包含一个分析维度
        has_dimension = any(
            k in config for k in ("trend", "strength", "volatility", "momentum")
        )
        if not has_dimension:
            raise ValueError("方案至少需要定义一个分析维度 (trend/strength/volatility/momentum)")

        return config

    def analyze(
        self,
        config: Dict[str, Any],
        klines: List[Dict],
        symbol: str = "",
    ) -> TrendResult:
        """
        执行趋势分析

        Args:
            config: parse_yaml() 返回的方案配置
            klines: K 线数据 (至少 200 根)
            symbol: 交易对

        Returns:
            TrendResult
        """
        if len(klines) < 50:
            return TrendResult(
                direction="unknown",
                strength="unknown",
                regime="insufficient_data",
                scheme_name=config.get("name", ""),
                symbol=symbol,
            )

        closes = [k["close"] for k in klines]
        result = TrendResult(
            scheme_name=config.get("name", ""),
            symbol=symbol,
            timeframe=config.get("interval", "1h"),
        )

        # 1. 趋势方向
        trend_cfg = config.get("trend", {})
        if trend_cfg:
            method = trend_cfg.get("method", "ema_alignment")
            params = trend_cfg.get("params", {})
            self._analyze_direction(result, closes, klines, method, params)

        # 2. 趋势强度
        strength_cfg = config.get("strength", {})
        if strength_cfg:
            method = strength_cfg.get("method", "adx")
            params = strength_cfg.get("params", {})
            self._analyze_strength(result, closes, klines, method, params)

        # 3. 波动率
        vol_cfg = config.get("volatility", {})
        if vol_cfg:
            method = vol_cfg.get("method", "bollinger_width")
            params = vol_cfg.get("params", {})
            self._analyze_volatility(result, closes, klines, method, params)

        # 4. 动量
        mom_cfg = config.get("momentum", {})
        if mom_cfg:
            method = mom_cfg.get("method", "rsi_macd")
            params = mom_cfg.get("params", {})
            self._analyze_momentum(result, closes, klines, method, params)

        # 5. 综合判断市场体制
        self._determine_regime(result)

        # 6. 策略建议
        advice_cfg = config.get("strategy_advice", {})
        self._apply_strategy_advice(result, advice_cfg)

        return result

    # ============================================================
    # 趋势方向分析
    # ============================================================

    def _analyze_direction(
        self, result: TrendResult, closes: list,
        klines: list, method: str, params: dict
    ):
        if method == "ema_alignment":
            self._direction_ema_alignment(result, closes, params)
        elif method == "ema_slope":
            self._direction_ema_slope(result, closes, params)
        elif method == "price_position":
            self._direction_price_position(result, closes, params)
        else:
            # 默认用 EMA 排列
            self._direction_ema_alignment(result, closes, params)

    def _direction_ema_alignment(self, result: TrendResult, closes: list, params: dict):
        """均线排列法: fast > medium > slow = 多头排列"""
        fast_p = params.get("fast", 20)
        medium_p = params.get("medium", 50)
        slow_p = params.get("slow", 200)

        fast = calculate_ema(closes, fast_p)
        medium = calculate_ema(closes, medium_p)
        slow = calculate_ema(closes, slow_p) if len(closes) >= slow_p else medium * 0.98

        if fast is None or medium is None:
            return

        price = closes[-1]

        # 计算方向分数
        score = 0
        if fast > medium:
            score += 30
        else:
            score -= 30
        if medium > slow:
            score += 30
        else:
            score -= 30
        if price > fast:
            score += 20
        else:
            score -= 20
        # 趋势角度: fast 相对于 n 根前的变化
        if len(closes) > fast_p + 5:
            old_fast = calculate_ema(closes[:-5], fast_p)
            if old_fast and fast:
                slope_pct = (fast - old_fast) / old_fast * 100
                score += min(max(slope_pct * 5, -20), 20)

        result.direction_score = round(score, 1)
        if score > 20:
            result.direction = "uptrend"
        elif score < -20:
            result.direction = "downtrend"
        else:
            result.direction = "ranging"
        result.direction_detail = (
            f"EMA{fast_p}={fast:.2f} EMA{medium_p}={medium:.2f} "
            f"EMA{slow_p}={slow:.2f} price={price:.2f} score={score:.1f}"
        )

    def _direction_ema_slope(self, result: TrendResult, closes: list, params: dict):
        """均线斜率法: EMA 近期斜率"""
        period = params.get("period", 50)
        lookback = params.get("lookback", 10)

        if len(closes) < period + lookback:
            return

        current = calculate_ema(closes, period)
        past = calculate_ema(closes[:-lookback], period)

        if current is None or past is None:
            return

        slope_pct = (current - past) / past * 100
        score = min(max(slope_pct * 20, -100), 100)

        result.direction_score = round(score, 1)
        if slope_pct > 0.5:
            result.direction = "uptrend"
        elif slope_pct < -0.5:
            result.direction = "downtrend"
        else:
            result.direction = "ranging"
        result.direction_detail = f"EMA{period} slope={slope_pct:.3f}%"

    def _direction_price_position(self, result: TrendResult, closes: list, params: dict):
        """价格位置法: 价格在 N 根 K 线 high/low 范围中的位置"""
        period = params.get("period", 100)
        data = closes[-period:] if len(closes) >= period else closes

        high = max(data)
        low = min(data)
        rng = high - low
        if rng == 0:
            return

        position = (closes[-1] - low) / rng  # 0=底部 1=顶部
        score = (position - 0.5) * 200  # -100 ~ +100

        result.direction_score = round(score, 1)
        if position > 0.65:
            result.direction = "uptrend"
        elif position < 0.35:
            result.direction = "downtrend"
        else:
            result.direction = "ranging"
        result.direction_detail = f"Price position={position:.2f} in {period}-bar range"

    # ============================================================
    # 趋势强度分析
    # ============================================================

    def _analyze_strength(
        self, result: TrendResult, closes: list,
        klines: list, method: str, params: dict
    ):
        if method == "adx":
            self._strength_adx(result, closes, klines, params)
        elif method == "ema_spread":
            self._strength_ema_spread(result, closes, params)
        else:
            self._strength_adx(result, closes, klines, params)

    def _strength_adx(self, result: TrendResult, closes: list, klines: list, params: dict):
        """ADX 法: 平均方向指数"""
        period = params.get("period", 14)
        strong_th = params.get("strong_threshold", 25)
        weak_th = params.get("weak_threshold", 15)

        if len(klines) < period * 3:
            return

        # 计算 ADX (简化版本: 用 ATR 和方向变化近似)
        atr = calculate_atr(klines, period)
        if atr is None or atr == 0:
            return

        # 用近 N 根 K 线的方向一致性近似 ADX
        recent = klines[-period:]
        up_moves = sum(1 for i in range(1, len(recent))
                       if recent[i]["close"] > recent[i-1]["close"])
        direction_ratio = abs(up_moves / len(recent) - 0.5) * 2  # 0=无方向 1=强方向

        # 结合 ATR 相对价格的比例
        atr_pct = atr / closes[-1] * 100
        adx_approx = direction_ratio * 50 + min(atr_pct * 10, 50)  # 0-100

        result.strength_score = round(adx_approx, 1)
        if adx_approx > strong_th:
            result.strength = "strong"
        elif adx_approx > weak_th:
            result.strength = "moderate"
        else:
            result.strength = "weak"
        result.strength_detail = f"ADX≈{adx_approx:.1f} ATR%={atr_pct:.3f}"

    def _strength_ema_spread(self, result: TrendResult, closes: list, params: dict):
        """均线扩散法: fast 和 slow EMA 的距离"""
        fast_p = params.get("fast", 20)
        slow_p = params.get("slow", 50)

        fast = calculate_ema(closes, fast_p)
        slow = calculate_ema(closes, slow_p)
        if fast is None or slow is None:
            return

        spread_pct = abs(fast - slow) / slow * 100
        score = min(spread_pct * 20, 100)

        result.strength_score = round(score, 1)
        if spread_pct > 2:
            result.strength = "strong"
        elif spread_pct > 0.5:
            result.strength = "moderate"
        else:
            result.strength = "weak"
        result.strength_detail = f"EMA spread={spread_pct:.3f}%"

    # ============================================================
    # 波动率分析
    # ============================================================

    def _analyze_volatility(
        self, result: TrendResult, closes: list,
        klines: list, method: str, params: dict
    ):
        if method == "bollinger_width":
            self._volatility_bollinger(result, closes, params)
        elif method == "atr_percent":
            self._volatility_atr_pct(result, closes, klines, params)
        else:
            self._volatility_bollinger(result, closes, params)

    def _volatility_bollinger(self, result: TrendResult, closes: list, params: dict):
        """布林带宽度法"""
        period = params.get("period", 20)
        high_th = params.get("high_threshold", 0.06)
        low_th = params.get("low_threshold", 0.02)

        bb = calculate_bollinger(closes, period)
        if "width" not in bb:
            return

        width = bb["width"]
        # 归一化 0-100
        score = min(width / high_th * 50, 100)

        result.volatility_score = round(score, 1)
        if width > high_th:
            result.volatility = "high"
        elif width > low_th:
            result.volatility = "normal"
        else:
            result.volatility = "low"
        result.volatility_detail = f"BB width={width:.4f}"

    def _volatility_atr_pct(self, result: TrendResult, closes: list, klines: list, params: dict):
        """ATR 百分比法"""
        period = params.get("period", 14)
        high_th = params.get("high_threshold", 3.0)
        low_th = params.get("low_threshold", 1.0)

        atr = calculate_atr(klines, period)
        if atr is None:
            return

        atr_pct = atr / closes[-1] * 100
        score = min(atr_pct / high_th * 50, 100)

        result.volatility_score = round(score, 1)
        if atr_pct > high_th:
            result.volatility = "high"
        elif atr_pct > low_th:
            result.volatility = "normal"
        else:
            result.volatility = "low"
        result.volatility_detail = f"ATR%={atr_pct:.3f}"

    # ============================================================
    # 动量分析
    # ============================================================

    def _analyze_momentum(
        self, result: TrendResult, closes: list,
        klines: list, method: str, params: dict
    ):
        if method == "rsi_macd":
            self._momentum_rsi_macd(result, closes, params)
        elif method == "rsi_only":
            self._momentum_rsi_only(result, closes, params)
        else:
            self._momentum_rsi_macd(result, closes, params)

    def _momentum_rsi_macd(self, result: TrendResult, closes: list, params: dict):
        """RSI + MACD 综合动量"""
        rsi_period = params.get("rsi_period", 14)
        rsi_ob = params.get("rsi_overbought", 70)
        rsi_os = params.get("rsi_oversold", 30)

        rsi = calculate_rsi(closes, rsi_period)
        macd_data = calculate_macd(closes)

        score = 0
        details = []

        if rsi is not None:
            # RSI 转换为 -50~+50 的分数
            rsi_score = (rsi - 50)  # 50 = neutral
            score += rsi_score
            details.append(f"RSI={rsi:.1f}")

        if "histogram" in macd_data:
            hist = macd_data["histogram"]
            # MACD histogram 归一化
            macd_score = min(max(hist / closes[-1] * 10000, -50), 50)
            score += macd_score
            details.append(f"MACD_hist={hist:.4f}")

        result.momentum_score = round(score, 1)
        if score > 20:
            result.momentum = "bullish"
        elif score < -20:
            result.momentum = "bearish"
        else:
            result.momentum = "neutral"
        result.momentum_detail = " | ".join(details)

    def _momentum_rsi_only(self, result: TrendResult, closes: list, params: dict):
        """纯 RSI 动量"""
        period = params.get("period", 14)
        rsi = calculate_rsi(closes, period)
        if rsi is None:
            return

        score = rsi - 50
        result.momentum_score = round(score, 1)
        if rsi > 60:
            result.momentum = "bullish"
        elif rsi < 40:
            result.momentum = "bearish"
        else:
            result.momentum = "neutral"
        result.momentum_detail = f"RSI={rsi:.1f}"

    # ============================================================
    # 综合判断
    # ============================================================

    def _determine_regime(self, result: TrendResult):
        """根据各维度判断市场体制"""
        d = result.direction
        s = result.strength
        v = result.volatility

        if d == "uptrend" and s in ("strong", "moderate"):
            result.regime = "trending_up"
            result.confidence = 60 + result.strength_score * 0.4
        elif d == "downtrend" and s in ("strong", "moderate"):
            result.regime = "trending_down"
            result.confidence = 60 + result.strength_score * 0.4
        elif v == "high":
            result.regime = "volatile"
            result.confidence = 50 + result.volatility_score * 0.3
        else:
            result.regime = "ranging"
            result.confidence = 40 + (100 - result.strength_score) * 0.3

        result.confidence = round(min(result.confidence, 100), 1)

    def _apply_strategy_advice(self, result: TrendResult, advice_cfg: dict):
        """根据配置的策略建议规则填充建议"""
        if not advice_cfg:
            # 使用默认建议
            advice_cfg = DEFAULT_STRATEGY_ADVICE

        regime = result.regime
        vol = result.volatility

        # 匹配 regime
        regime_key_map = {
            "trending_up": "uptrend_strong",
            "trending_down": "downtrend_strong",
            "ranging": "ranging",
            "volatile": "high_volatility",
        }
        key = regime_key_map.get(regime, "ranging")
        advice = advice_cfg.get(key, {})

        result.suitable_strategies = advice.get("suitable", [])
        result.unsuitable_strategies = advice.get("unsuitable", [])

        # 额外: 高波动时叠加建议
        if vol == "high" and regime != "volatile":
            vol_advice = advice_cfg.get("high_volatility", {})
            result.suitable_strategies = list(set(
                result.suitable_strategies + vol_advice.get("suitable", [])
            ))


# ============================================================
# 默认配置
# ============================================================


DEFAULT_STRATEGY_ADVICE = {
    "uptrend_strong": {
        "suitable": ["趋势跟踪", "突破", "均线策略", "金叉做多"],
        "unsuitable": ["均值回归", "逆势做空"],
    },
    "downtrend_strong": {
        "suitable": ["趋势跟踪做空", "反弹做空", "死叉策略"],
        "unsuitable": ["做多突破", "抄底"],
    },
    "ranging": {
        "suitable": ["RSI超买超卖", "均值回归", "网格交易", "布林带策略"],
        "unsuitable": ["趋势跟踪", "突破策略"],
    },
    "high_volatility": {
        "suitable": ["宽止损策略", "波动率突破", "短线波段"],
        "unsuitable": ["窄止损策略", "小仓位趋势"],
    },
}


# 预置方案 YAML
PRESET_SCHEMES = {
    "standard": {
        "name": "标准趋势",
        "yaml": '''name: "标准趋势分析"
interval: "1h"

trend:
  method: "ema_alignment"
  params:
    fast: 20
    medium: 50
    slow: 200

strength:
  method: "adx"
  params:
    period: 14
    strong_threshold: 25
    weak_threshold: 15

volatility:
  method: "bollinger_width"
  params:
    period: 20
    high_threshold: 0.06
    low_threshold: 0.02

momentum:
  method: "rsi_macd"
  params:
    rsi_period: 14
    rsi_overbought: 70
    rsi_oversold: 30
'''
    },
    "momentum": {
        "name": "动量驱动",
        "yaml": '''name: "动量驱动分析"
interval: "1h"

trend:
  method: "ema_slope"
  params:
    period: 50
    lookback: 10

strength:
  method: "ema_spread"
  params:
    fast: 20
    slow: 50

volatility:
  method: "atr_percent"
  params:
    period: 14
    high_threshold: 3.0
    low_threshold: 1.0

momentum:
  method: "rsi_macd"
  params:
    rsi_period: 14
    rsi_overbought: 65
    rsi_oversold: 35
'''
    },
    "conservative": {
        "name": "保守型",
        "yaml": '''name: "保守型趋势分析"
interval: "4h"

trend:
  method: "price_position"
  params:
    period: 100

strength:
  method: "adx"
  params:
    period: 14
    strong_threshold: 30
    weak_threshold: 20

volatility:
  method: "bollinger_width"
  params:
    period: 20
    high_threshold: 0.08
    low_threshold: 0.03

momentum:
  method: "rsi_only"
  params:
    period: 14
'''
    },
}
