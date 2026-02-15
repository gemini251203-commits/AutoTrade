"""
Indicator Engine - 技术指标 + K线形态 + 支撑阻力
==================================================
量化策略的基础工具层

模块:
1. 技术指标计算 (RSI, MACD, EMA, 布林带, KDJ, ATR, OBV)
2. 支撑线 / 阻力线检测
3. K 线形态识别 (Pinbar, 锤子, 吞没, 十字星等)
4. 指标注册表 (供策略引擎按名称调用)

设计原则:
- 所有函数接收 List[Dict] 格式的 K 线数据
- 每根 K 线: {"open_time", "open", "high", "low", "close", "volume"}
- 返回值为 float / bool / dict，方便条件比较
"""

from typing import List, Dict, Optional, Tuple, Any
from loguru import logger
import math


# ============================================================
# 1. 技术指标计算
# ============================================================

def calculate_ema(closes: List[float], period: int) -> Optional[float]:
    """
    指数移动平均线 (EMA)
    
    EMA 比 SMA 对近期价格更敏感，适合趋势跟踪
    """
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 6)


def calculate_ema_series(closes: List[float], period: int) -> List[float]:
    """计算 EMA 序列（用于交叉检测）"""
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    ema_series = [closes[0]]
    for price in closes[1:]:
        ema_series.append(price * k + ema_series[-1] * (1 - k))
    return ema_series


def calculate_sma(closes: List[float], period: int) -> Optional[float]:
    """简单移动平均线 (SMA)"""
    if len(closes) < period:
        return None
    return round(sum(closes[-period:]) / period, 6)


def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """
    相对强弱指数 (RSI)
    
    RSI > 70: 超买区域
    RSI < 30: 超卖区域
    """
    if len(closes) < period + 1:
        return None
    
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = changes[-(period):]
    
    gains = [c if c > 0 else 0 for c in recent]
    losses = [-c if c < 0 else 0 for c in recent]
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_macd(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[Dict[str, float]]:
    """
    MACD 指标
    
    返回: {"macd": float, "signal": float, "histogram": float}
    - histogram > 0: 多头动能
    - histogram < 0: 空头动能
    - histogram 由负转正: 金叉信号
    """
    if len(closes) < slow + signal:
        return None
    
    ema_fast = calculate_ema_series(closes, fast)
    ema_slow = calculate_ema_series(closes, slow)
    
    # MACD 线 = 快 EMA - 慢 EMA（取最后 signal+1 个点）
    min_len = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-(min_len - i)] - ema_slow[-(min_len - i)] for i in range(min_len)]
    
    # 信号线 = MACD 线的 EMA
    if len(macd_line) < signal:
        return None
    
    signal_line = calculate_ema_series(macd_line, signal)
    
    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    histogram = macd_val - signal_val
    
    return {
        "macd": round(macd_val, 6),
        "signal": round(signal_val, 6),
        "histogram": round(histogram, 6),
    }


def calculate_bollinger(
    closes: List[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> Optional[Dict[str, float]]:
    """
    布林带 (Bollinger Bands)
    
    返回: {"upper": float, "middle": float, "lower": float, "width": float}
    - 价格触及上轨: 可能超买
    - 价格触及下轨: 可能超卖
    - width 缩窄: 即将变盘
    """
    if len(closes) < period:
        return None
    
    recent = closes[-period:]
    middle = sum(recent) / period
    
    variance = sum((x - middle) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    width = (upper - lower) / middle if middle > 0 else 0
    
    return {
        "upper": round(upper, 6),
        "middle": round(middle, 6),
        "lower": round(lower, 6),
        "width": round(width, 6),
    }


def calculate_kdj(
    klines: List[Dict],
    k_period: int = 9,
    d_period: int = 3,
) -> Optional[Dict[str, float]]:
    """
    KDJ 随机指标
    
    返回: {"k": float, "d": float, "j": float}
    - K > 80, D > 80: 超买
    - K < 20, D < 20: 超卖  
    - J > 100: 极度超买
    - J < 0: 极度超卖
    """
    if len(klines) < k_period:
        return None
    
    recent = klines[-k_period:]
    highest = max(k["high"] for k in recent)
    lowest = min(k["low"] for k in recent)
    
    if highest == lowest:
        rsv = 50.0
    else:
        current_close = klines[-1]["close"]
        rsv = (current_close - lowest) / (highest - lowest) * 100
    
    # 简化: 用当前 RSV 估算 K, D
    k_val = rsv  # 首次直接用 RSV
    d_val = k_val  # 首次 D = K
    
    # 如果有足够数据，用指数平滑
    if len(klines) >= k_period + d_period:
        k_val = (2 / 3) * 50 + (1 / 3) * rsv  # 简化
        d_val = (2 / 3) * 50 + (1 / 3) * k_val
    
    j_val = 3 * k_val - 2 * d_val
    
    return {
        "k": round(k_val, 2),
        "d": round(d_val, 2),
        "j": round(j_val, 2),
    }


def calculate_atr(klines: List[Dict], period: int = 14) -> Optional[float]:
    """
    平均真实波幅 (ATR)
    
    用于止损设置和波动率衡量
    ATR 越大 = 波动越大
    """
    if len(klines) < period + 1:
        return None
    
    true_ranges = []
    for i in range(1, len(klines)):
        high = klines[i]["high"]
        low = klines[i]["low"]
        prev_close = klines[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    
    return round(sum(true_ranges[-period:]) / period, 6)


def calculate_obv(klines: List[Dict]) -> Optional[float]:
    """
    成交量能量潮 (OBV)
    
    价涨量增: OBV 上升 → 多头
    价跌量增: OBV 下降 → 空头
    """
    if len(klines) < 2:
        return None
    
    obv = 0.0
    for i in range(1, len(klines)):
        if klines[i]["close"] > klines[i - 1]["close"]:
            obv += klines[i]["volume"]
        elif klines[i]["close"] < klines[i - 1]["close"]:
            obv -= klines[i]["volume"]
    
    return round(obv, 2)


def calculate_volume_ratio(klines: List[Dict], period: int = 5) -> Optional[float]:
    """
    量比 = 当前成交量 / 过去 N 期平均成交量
    
    > 2.0: 显著放量
    < 0.5: 显著缩量
    """
    if len(klines) < period + 1:
        return None
    
    volumes = [k["volume"] for k in klines]
    avg = sum(volumes[-period - 1:-1]) / period
    if avg == 0:
        return None
    return round(volumes[-1] / avg, 2)


# ============================================================
# 2. 支撑线 / 阻力线检测
# ============================================================

def find_pivot_points(
    klines: List[Dict],
    left: int = 5,
    right: int = 5,
) -> Dict[str, List[Dict]]:
    """
    寻找枢轴点 (Pivot Points) — 支撑/阻力的基础
    
    枢轴高点: 某根 K 线的 high 比左边 left 根和右边 right 根的 high 都高
    枢轴低点: 某根 K 线的 low 比左边 left 根和右边 right 根的 low 都低
    
    Args:
        klines: K 线数据
        left: 左侧需要多少根 K 线确认
        right: 右侧需要多少根 K 线确认
    
    Returns:
        {"highs": [...], "lows": [...]}
        每个元素: {"price": float, "index": int, "time": open_time}
    """
    highs = []
    lows = []
    
    if len(klines) < left + right + 1:
        return {"highs": highs, "lows": lows}
    
    for i in range(left, len(klines) - right):
        # 检查枢轴高点
        is_pivot_high = True
        for j in range(1, left + 1):
            if klines[i - j]["high"] >= klines[i]["high"]:
                is_pivot_high = False
                break
        if is_pivot_high:
            for j in range(1, right + 1):
                if klines[i + j]["high"] >= klines[i]["high"]:
                    is_pivot_high = False
                    break
        
        if is_pivot_high:
            highs.append({
                "price": klines[i]["high"],
                "index": i,
                "time": klines[i].get("open_time"),
            })
        
        # 检查枢轴低点
        is_pivot_low = True
        for j in range(1, left + 1):
            if klines[i - j]["low"] <= klines[i]["low"]:
                is_pivot_low = False
                break
        if is_pivot_low:
            for j in range(1, right + 1):
                if klines[i + j]["low"] <= klines[i]["low"]:
                    is_pivot_low = False
                    break
        
        if is_pivot_low:
            lows.append({
                "price": klines[i]["low"],
                "index": i,
                "time": klines[i].get("open_time"),
            })
    
    return {"highs": highs, "lows": lows}


def cluster_levels(
    prices: List[float],
    tolerance_pct: float = 0.5,
) -> List[Dict[str, Any]]:
    """
    将价格聚类为支撑/阻力区域
    
    如果多个枢轴点价格在 tolerance_pct% 的范围内，
    认为它们属于同一个支撑/阻力区域 → 该区域越被触碰就越"强"
    
    Args:
        prices: 枢轴点价格列表
        tolerance_pct: 聚类容差百分比 (默认 0.5%)
    
    Returns:
        每个区域: {"level": 平均价, "strength": 触碰次数, "prices": [原始价格]}
    """
    if not prices:
        return []
    
    sorted_prices = sorted(prices)
    clusters: List[Dict[str, Any]] = []
    current_cluster: List[float] = [sorted_prices[0]]
    
    for price in sorted_prices[1:]:
        cluster_avg = sum(current_cluster) / len(current_cluster)
        if abs(price - cluster_avg) / cluster_avg * 100 <= tolerance_pct:
            current_cluster.append(price)
        else:
            clusters.append({
                "level": round(sum(current_cluster) / len(current_cluster), 6),
                "strength": len(current_cluster),
                "prices": current_cluster,
            })
            current_cluster = [price]
    
    # 最后一个 cluster
    clusters.append({
        "level": round(sum(current_cluster) / len(current_cluster), 6),
        "strength": len(current_cluster),
        "prices": current_cluster,
    })
    
    return clusters


def find_support_resistance(
    klines: List[Dict],
    pivot_left: int = 5,
    pivot_right: int = 5,
    cluster_tolerance: float = 0.5,
    min_strength: int = 2,
) -> Dict[str, List[Dict]]:
    """
    综合支撑线 / 阻力线检测
    
    流程:
    1. 找枢轴高点和低点
    2. 对高点和低点分别聚类
    3. 过滤出强度 >= min_strength 的有效水平
    4. 标注当前价格相对位置
    
    Args:
        klines: K 线数据 (建议 100+ 根)
        pivot_left/right: 枢轴点确认窗口
        cluster_tolerance: 聚类容差 %
        min_strength: 最低要求触碰次数
    
    Returns:
        {
            "support": [{"level": 价格, "strength": 强度, "distance_pct": 距离%}],
            "resistance": [{"level": 价格, "strength": 强度, "distance_pct": 距离%}],
            "current_price": float,
            "nearest_support": float | None,
            "nearest_resistance": float | None,
        }
    """
    if len(klines) < pivot_left + pivot_right + 1:
        return {
            "support": [], "resistance": [],
            "current_price": klines[-1]["close"] if klines else 0,
            "nearest_support": None, "nearest_resistance": None,
        }
    
    current_price = klines[-1]["close"]
    
    # Step 1: 找枢轴点
    pivots = find_pivot_points(klines, pivot_left, pivot_right)
    
    # Step 2: 把所有枢轴点合并后聚类
    all_pivot_prices = (
        [p["price"] for p in pivots["highs"]] +
        [p["price"] for p in pivots["lows"]]
    )
    clusters = cluster_levels(all_pivot_prices, cluster_tolerance)
    
    # Step 3: 按当前价格分类为支撑/阻力
    support_levels = []
    resistance_levels = []
    
    for c in clusters:
        if c["strength"] < min_strength:
            continue
        
        distance_pct = round((c["level"] - current_price) / current_price * 100, 2)
        level_info = {
            "level": c["level"],
            "strength": c["strength"],
            "distance_pct": distance_pct,
        }
        
        if c["level"] < current_price:
            support_levels.append(level_info)
        else:
            resistance_levels.append(level_info)
    
    # 按距离排序 (支撑: 近→远, 阻力: 近→远)
    support_levels.sort(key=lambda x: abs(x["distance_pct"]))
    resistance_levels.sort(key=lambda x: abs(x["distance_pct"]))
    
    return {
        "support": support_levels,
        "resistance": resistance_levels,
        "current_price": current_price,
        "nearest_support": support_levels[0]["level"] if support_levels else None,
        "nearest_resistance": resistance_levels[0]["level"] if resistance_levels else None,
    }


def near_support(klines: List[Dict], tolerance_pct: float = 1.0) -> bool:
    """
    当前价格是否接近支撑位
    
    用于策略条件: indicator: near_support, compare: "==", value: true
    """
    sr = find_support_resistance(klines)
    if sr["nearest_support"] is None:
        return False
    distance = abs(sr["current_price"] - sr["nearest_support"]) / sr["current_price"] * 100
    return distance <= tolerance_pct


def near_resistance(klines: List[Dict], tolerance_pct: float = 1.0) -> bool:
    """
    当前价格是否接近阻力位
    """
    sr = find_support_resistance(klines)
    if sr["nearest_resistance"] is None:
        return False
    distance = abs(sr["current_price"] - sr["nearest_resistance"]) / sr["current_price"] * 100
    return distance <= tolerance_pct


# ============================================================
# 3. K 线形态检测
# ============================================================

def detect_pinbar(klines: List[Dict], wick_ratio: float = 2.0) -> bool:
    """
    Pinbar (针形反转线)
    
    特征: 一端影线长度 >= 实体的 wick_ratio 倍
    - 看涨 Pinbar: 长下影线（卖方尝试打压但被买方收回）
    - 看跌 Pinbar: 长上影线
    
    Args:
        wick_ratio: 影线/实体比 (默认 2 倍)
    """
    if len(klines) < 1:
        return False
    
    k = klines[-1]
    body = abs(k["close"] - k["open"])
    if body == 0:
        body = 0.0001  # 防止除零
    
    upper_wick = k["high"] - max(k["close"], k["open"])
    lower_wick = min(k["close"], k["open"]) - k["low"]
    longest_wick = max(upper_wick, lower_wick)
    
    return longest_wick >= body * wick_ratio


def detect_bullish_pinbar(klines: List[Dict], wick_ratio: float = 2.0) -> bool:
    """看涨 Pinbar: 长下影线 (下方买盘支撑)"""
    if len(klines) < 1:
        return False
    
    k = klines[-1]
    body = abs(k["close"] - k["open"])
    if body == 0:
        body = 0.0001
    
    lower_wick = min(k["close"], k["open"]) - k["low"]
    upper_wick = k["high"] - max(k["close"], k["open"])
    
    return (
        lower_wick >= body * wick_ratio
        and lower_wick > upper_wick * 1.5  # 下影线明显长于上影线
    )


def detect_bearish_pinbar(klines: List[Dict], wick_ratio: float = 2.0) -> bool:
    """看跌 Pinbar: 长上影线 (上方抛压)"""
    if len(klines) < 1:
        return False
    
    k = klines[-1]
    body = abs(k["close"] - k["open"])
    if body == 0:
        body = 0.0001
    
    upper_wick = k["high"] - max(k["close"], k["open"])
    lower_wick = min(k["close"], k["open"]) - k["low"]
    
    return (
        upper_wick >= body * wick_ratio
        and upper_wick > lower_wick * 1.5
    )


def detect_hammer(klines: List[Dict]) -> bool:
    """
    锤子线 (Hammer) — 底部反转信号
    
    特征:
    - 下影线 >= 实体的 2 倍
    - 上影线很短 (< 实体的 30%)
    - 出现在下跌趋势后效果更好
    """
    if len(klines) < 1:
        return False
    
    k = klines[-1]
    body = abs(k["close"] - k["open"])
    if body == 0:
        body = 0.0001
    
    upper_wick = k["high"] - max(k["close"], k["open"])
    lower_wick = min(k["close"], k["open"]) - k["low"]
    
    return (
        lower_wick >= body * 2
        and upper_wick <= body * 0.3
    )


def detect_inverted_hammer(klines: List[Dict]) -> bool:
    """
    倒锤子线 (Inverted Hammer) — 底部信号
    
    特征:
    - 上影线 >= 实体的 2 倍
    - 下影线很短
    """
    if len(klines) < 1:
        return False
    
    k = klines[-1]
    body = abs(k["close"] - k["open"])
    if body == 0:
        body = 0.0001
    
    upper_wick = k["high"] - max(k["close"], k["open"])
    lower_wick = min(k["close"], k["open"]) - k["low"]
    
    return (
        upper_wick >= body * 2
        and lower_wick <= body * 0.3
    )


def detect_doji(klines: List[Dict], body_ratio: float = 0.05) -> bool:
    """
    十字星 (Doji) — 多空平衡，可能变盘
    
    特征: 实体极小 (< 整根K线高度的 body_ratio)
    """
    if len(klines) < 1:
        return False
    
    k = klines[-1]
    body = abs(k["close"] - k["open"])
    total_range = k["high"] - k["low"]
    
    if total_range == 0:
        return True  # 完全没有波动也算十字
    
    return body / total_range <= body_ratio


def detect_engulfing(klines: List[Dict]) -> bool:
    """
    看涨吞没 (Bullish Engulfing)
    
    特征:
    - 前一根阴线 (close < open)
    - 当前阳线 (close > open)
    - 当前实体完全包裹前一根实体
    """
    if len(klines) < 2:
        return False
    
    prev, curr = klines[-2], klines[-1]
    
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    
    return (
        prev_bearish
        and curr_bullish
        and curr["close"] > prev["open"]
        and curr["open"] < prev["close"]
    )


def detect_bearish_engulfing(klines: List[Dict]) -> bool:
    """
    看跌吞没 (Bearish Engulfing)
    
    特征:
    - 前一根阳线 (close > open)
    - 当前阴线 (close < open)
    - 当前实体完全包裹前一根实体
    """
    if len(klines) < 2:
        return False
    
    prev, curr = klines[-2], klines[-1]
    
    prev_bullish = prev["close"] > prev["open"]
    curr_bearish = curr["close"] < curr["open"]
    
    return (
        prev_bullish
        and curr_bearish
        and curr["open"] > prev["close"]
        and curr["close"] < prev["open"]
    )


def detect_morning_star(klines: List[Dict]) -> bool:
    """
    启明星 (Morning Star) — 底部反转三根组合
    
    1. 大阴线
    2. 小实体（十字星或小阳/阴线）
    3. 大阳线
    """
    if len(klines) < 3:
        return False
    
    first, second, third = klines[-3], klines[-2], klines[-1]
    
    first_range = abs(first["close"] - first["open"])
    second_range = abs(second["close"] - second["open"])
    third_range = abs(third["close"] - third["open"])
    
    first_bearish = first["close"] < first["open"]
    third_bullish = third["close"] > third["open"]
    small_body = second_range < first_range * 0.3
    
    return (
        first_bearish
        and small_body
        and third_bullish
        and third_range > first_range * 0.5
        and third["close"] > (first["open"] + first["close"]) / 2
    )


def detect_evening_star(klines: List[Dict]) -> bool:
    """
    黄昏星 (Evening Star) — 顶部反转三根组合
    
    1. 大阳线
    2. 小实体
    3. 大阴线
    """
    if len(klines) < 3:
        return False
    
    first, second, third = klines[-3], klines[-2], klines[-1]
    
    first_range = abs(first["close"] - first["open"])
    second_range = abs(second["close"] - second["open"])
    third_range = abs(third["close"] - third["open"])
    
    first_bullish = first["close"] > first["open"]
    third_bearish = third["close"] < third["open"]
    small_body = second_range < first_range * 0.3
    
    return (
        first_bullish
        and small_body
        and third_bearish
        and third_range > first_range * 0.5
        and third["close"] < (first["open"] + first["close"]) / 2
    )


def detect_three_white_soldiers(klines: List[Dict]) -> bool:
    """
    三白兵 (Three White Soldiers) — 强看涨信号
    
    连续三根阳线, 每根的收盘价高于前一根的收盘价
    且每根的开盘价在前一根实体内部
    """
    if len(klines) < 3:
        return False
    
    k1, k2, k3 = klines[-3], klines[-2], klines[-1]
    
    all_bullish = (
        k1["close"] > k1["open"]
        and k2["close"] > k2["open"]
        and k3["close"] > k3["open"]
    )
    
    ascending_close = k3["close"] > k2["close"] > k1["close"]
    
    # 每根的开盘在前一根实体内
    k2_open_in_k1 = k1["open"] <= k2["open"] <= k1["close"]
    k3_open_in_k2 = k2["open"] <= k3["open"] <= k2["close"]
    
    return all_bullish and ascending_close and k2_open_in_k1 and k3_open_in_k2


def detect_three_black_crows(klines: List[Dict]) -> bool:
    """
    三只乌鸦 (Three Black Crows) — 强看跌信号
    
    连续三根阴线, 每根的收盘价低于前一根
    """
    if len(klines) < 3:
        return False
    
    k1, k2, k3 = klines[-3], klines[-2], klines[-1]
    
    all_bearish = (
        k1["close"] < k1["open"]
        and k2["close"] < k2["open"]
        and k3["close"] < k3["open"]
    )
    
    descending_close = k3["close"] < k2["close"] < k1["close"]
    
    k2_open_in_k1 = k1["close"] <= k2["open"] <= k1["open"]
    k3_open_in_k2 = k2["close"] <= k3["open"] <= k2["open"]
    
    return all_bearish and descending_close and k2_open_in_k1 and k3_open_in_k2


def detect_pinbar_at_support(
    klines: List[Dict],
    support_tolerance_pct: float = 1.5,
) -> bool:
    """
    Pinbar + 支撑位组合信号
    
    在关键支撑位附近出现看涨 Pinbar = 高概率反转
    这是 Pinbar 策略中最有意义的形态
    """
    if not detect_bullish_pinbar(klines):
        return False
    
    sr = find_support_resistance(klines[:-1])  # 排除当前 K 线
    if sr["nearest_support"] is None:
        return False
    
    price = klines[-1]["low"]
    distance = abs(price - sr["nearest_support"]) / sr["nearest_support"] * 100
    return distance <= support_tolerance_pct


def detect_pinbar_at_resistance(
    klines: List[Dict],
    resistance_tolerance_pct: float = 1.5,
) -> bool:
    """
    Pinbar + 阻力位组合信号
    
    在阻力位附近出现看跌 Pinbar = 高概率回落
    """
    if not detect_bearish_pinbar(klines):
        return False
    
    sr = find_support_resistance(klines[:-1])
    if sr["nearest_resistance"] is None:
        return False
    
    price = klines[-1]["high"]
    distance = abs(price - sr["nearest_resistance"]) / sr["nearest_resistance"] * 100
    return distance <= resistance_tolerance_pct


# ============================================================
# 4. 辅助检测函数
# ============================================================

def detect_golden_cross(
    closes: List[float],
    fast_period: int = 20,
    slow_period: int = 50,
) -> bool:
    """
    均线金叉 — 快线上穿慢线
    
    即: 前一根 K 线 fast < slow, 当前 K 线 fast > slow
    """
    if len(closes) < slow_period + 2:
        return False
    
    fast_prev = calculate_ema(closes[:-1], fast_period)
    fast_curr = calculate_ema(closes, fast_period)
    slow_prev = calculate_ema(closes[:-1], slow_period)
    slow_curr = calculate_ema(closes, slow_period)
    
    if any(v is None for v in [fast_prev, fast_curr, slow_prev, slow_curr]):
        return False
    
    return fast_prev <= slow_prev and fast_curr > slow_curr


def detect_death_cross(
    closes: List[float],
    fast_period: int = 20,
    slow_period: int = 50,
) -> bool:
    """均线死叉 — 快线下穿慢线"""
    if len(closes) < slow_period + 2:
        return False
    
    fast_prev = calculate_ema(closes[:-1], fast_period)
    fast_curr = calculate_ema(closes, fast_period)
    slow_prev = calculate_ema(closes[:-1], slow_period)
    slow_curr = calculate_ema(closes, slow_period)
    
    if any(v is None for v in [fast_prev, fast_curr, slow_prev, slow_curr]):
        return False
    
    return fast_prev >= slow_prev and fast_curr < slow_curr


def detect_macd_golden_cross(closes: List[float]) -> bool:
    """MACD 金叉 — MACD 线上穿信号线 (histogram 由负转正)"""
    if len(closes) < 35 + 2:
        return False
    
    macd_prev = calculate_macd(closes[:-1])
    macd_curr = calculate_macd(closes)
    
    if macd_prev is None or macd_curr is None:
        return False
    
    return macd_prev["histogram"] <= 0 and macd_curr["histogram"] > 0


def detect_macd_death_cross(closes: List[float]) -> bool:
    """MACD 死叉 — MACD 线下穿信号线"""
    if len(closes) < 35 + 2:
        return False
    
    macd_prev = calculate_macd(closes[:-1])
    macd_curr = calculate_macd(closes)
    
    if macd_prev is None or macd_curr is None:
        return False
    
    return macd_prev["histogram"] >= 0 and macd_curr["histogram"] < 0


# ============================================================
# 5. 指标注册表 — 策略引擎通过名称调用
# ============================================================

def _make_indicator_registry() -> Dict[str, Any]:
    """
    构建指标注册表
    
    每个条目: name → callable(klines) → value
    策略引擎会根据 YAML 中的 indicator 名称在这里查找
    """
    return {
        # --- 技术指标 (返回 float) ---
        "rsi": lambda klines: calculate_rsi([k["close"] for k in klines]),
        "rsi_7": lambda klines: calculate_rsi([k["close"] for k in klines], 7),
        
        "macd": lambda klines: (calculate_macd([k["close"] for k in klines]) or {}).get("macd"),
        "macd_signal": lambda klines: (calculate_macd([k["close"] for k in klines]) or {}).get("signal"),
        "macd_histogram": lambda klines: (calculate_macd([k["close"] for k in klines]) or {}).get("histogram"),
        
        "ema_5": lambda klines: calculate_ema([k["close"] for k in klines], 5),
        "ema_10": lambda klines: calculate_ema([k["close"] for k in klines], 10),
        "ema_20": lambda klines: calculate_ema([k["close"] for k in klines], 20),
        "ema_50": lambda klines: calculate_ema([k["close"] for k in klines], 50),
        "ema_99": lambda klines: calculate_ema([k["close"] for k in klines], 99),
        "ema_200": lambda klines: calculate_ema([k["close"] for k in klines], 200),
        
        "sma_20": lambda klines: calculate_sma([k["close"] for k in klines], 20),
        "sma_50": lambda klines: calculate_sma([k["close"] for k in klines], 50),
        
        "bollinger_upper": lambda klines: (calculate_bollinger([k["close"] for k in klines]) or {}).get("upper"),
        "bollinger_lower": lambda klines: (calculate_bollinger([k["close"] for k in klines]) or {}).get("lower"),
        "bollinger_middle": lambda klines: (calculate_bollinger([k["close"] for k in klines]) or {}).get("middle"),
        "bollinger_width": lambda klines: (calculate_bollinger([k["close"] for k in klines]) or {}).get("width"),
        
        "kdj_k": lambda klines: (calculate_kdj(klines) or {}).get("k"),
        "kdj_d": lambda klines: (calculate_kdj(klines) or {}).get("d"),
        "kdj_j": lambda klines: (calculate_kdj(klines) or {}).get("j"),
        
        "atr": lambda klines: calculate_atr(klines),
        "obv": lambda klines: calculate_obv(klines),
        "volume_ratio": lambda klines: calculate_volume_ratio(klines),
        
        # --- 当前价格 ---
        "close": lambda klines: klines[-1]["close"],
        "open": lambda klines: klines[-1]["open"],
        "high": lambda klines: klines[-1]["high"],
        "low": lambda klines: klines[-1]["low"],
        "volume": lambda klines: klines[-1]["volume"],
        
        # --- 支撑 / 阻力 (返回 float) ---
        "nearest_support": lambda klines: find_support_resistance(klines).get("nearest_support"),
        "nearest_resistance": lambda klines: find_support_resistance(klines).get("nearest_resistance"),
        
        # --- K 线形态 (返回 bool) ---
        "pattern_pinbar": detect_pinbar,
        "pattern_bullish_pinbar": detect_bullish_pinbar,
        "pattern_bearish_pinbar": detect_bearish_pinbar,
        "pattern_hammer": detect_hammer,
        "pattern_inverted_hammer": detect_inverted_hammer,
        "pattern_doji": detect_doji,
        "pattern_engulfing": detect_engulfing,
        "pattern_bearish_engulfing": detect_bearish_engulfing,
        "pattern_morning_star": detect_morning_star,
        "pattern_evening_star": detect_evening_star,
        "pattern_three_soldiers": detect_three_white_soldiers,
        "pattern_three_crows": detect_three_black_crows,
        
        # --- 组合信号 (返回 bool) ---
        "pinbar_at_support": detect_pinbar_at_support,
        "pinbar_at_resistance": detect_pinbar_at_resistance,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "golden_cross": lambda klines: detect_golden_cross([k["close"] for k in klines]),
        "death_cross": lambda klines: detect_death_cross([k["close"] for k in klines]),
        "macd_golden_cross": lambda klines: detect_macd_golden_cross([k["close"] for k in klines]),
        "macd_death_cross": lambda klines: detect_macd_death_cross([k["close"] for k in klines]),
    }


# 全局指标注册表
INDICATOR_REGISTRY = _make_indicator_registry()


def get_indicator(name: str, klines: List[Dict]) -> Any:
    """
    按名称获取指标值
    
    Args:
        name: 指标名称 (如 "rsi", "pattern_pinbar")
        klines: K 线数据
    
    Returns:
        指标值 (float/bool/None)
    
    Raises:
        KeyError: 未知的指标名称
    """
    if name not in INDICATOR_REGISTRY:
        raise KeyError(
            f"未知指标: '{name}'。可用指标: {sorted(INDICATOR_REGISTRY.keys())}"
        )
    try:
        return INDICATOR_REGISTRY[name](klines)
    except Exception as e:
        logger.warning(f"[Indicator] 计算 {name} 出错: {e}")
        return None


def calculate_all_indicators(klines: List[Dict]) -> Dict[str, Any]:
    """
    一次性计算所有常用指标快照
    
    用于 AI 审核员注入上下文
    """
    closes = [k["close"] for k in klines]
    
    result = {
        "price": {
            "close": klines[-1]["close"],
            "open": klines[-1]["open"],
            "high": klines[-1]["high"],
            "low": klines[-1]["low"],
        },
        "rsi": calculate_rsi(closes),
        "macd": calculate_macd(closes),
        "ema": {
            "ema_20": calculate_ema(closes, 20),
            "ema_50": calculate_ema(closes, 50),
        },
        "bollinger": calculate_bollinger(closes),
        "kdj": calculate_kdj(klines),
        "atr": calculate_atr(klines),
        "volume_ratio": calculate_volume_ratio(klines),
        "support_resistance": find_support_resistance(klines),
    }
    
    # 检测当前的 K 线形态
    patterns = {}
    pattern_names = [k for k in INDICATOR_REGISTRY if k.startswith("pattern_")]
    for name in pattern_names:
        patterns[name] = INDICATOR_REGISTRY[name](klines)
    result["patterns"] = patterns
    
    return result
