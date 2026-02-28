"""
Chanlun Utils — 轻量级缠论几何计算
====================================
纯 Python 实现，不依赖第三方缠论库。

功能:
- 包含处理 (K线合并)
- 顶底分型识别
- 笔构建
- MACD 背驰检测
- 一键分析入口

设计原则:
  Python 负责几何计算 → 输出结构化 JSON → AI 负责逻辑推理
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
import math


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MergedBar:
    """包含处理后的合并K线"""
    high: float
    low: float
    open_time: str          # 起始时间
    close_time: str         # 结束时间
    bar_count: int = 1      # 包含的原始 K 线数
    index: int = 0          # 在合并序列中的位置


@dataclass
class Fractal:
    """顶底分型"""
    type: str               # "top" | "bottom"
    price: float            # 顶分型=high, 底分型=low
    index: int              # 合并K线序列中的位置
    bar_count: int = 1      # 该合并bar包含的原始K线数
    timestamp: str = ""     # 时间


@dataclass
class Stroke:
    """笔"""
    direction: str          # "up" | "down"
    start_price: float
    end_price: float
    start_time: str = ""
    end_time: str = ""
    start_index: int = 0
    end_index: int = 0
    bar_span: int = 0       # 跨越的合并K线数


@dataclass
class DivergenceResult:
    """MACD 背驰检测结果"""
    has_top_divergence: bool = False     # 顶背驰（价格新高但动能衰竭）
    has_bottom_divergence: bool = False  # 底背驰（价格新低但动能衰竭）
    current_area: float = 0.0
    previous_area: float = 0.0
    area_ratio: float = 1.0             # current / previous, <1 = 衰竭
    detail: str = ""


# ============================================================
# 1. 包含处理
# ============================================================

def merge_inclusive_bars(klines: List[dict]) -> List[MergedBar]:
    """
    包含处理：消除K线包含关系
    
    规则：
    - 包含判定: a.high >= b.high AND a.low <= b.low (或反之)
    - 上升方向：取高的 high，取高的 low (向上合并)
    - 下降方向：取低的 high，取低的 low (向下合并)
    
    Args:
        klines: OHLCV K线列表 [{"open_time", "high", "low", ...}, ...]
    
    Returns:
        合并后的 MergedBar 列表
    """
    if len(klines) < 3:
        return []
    
    merged: List[MergedBar] = []
    
    for i, k in enumerate(klines):
        h = float(k.get("high", k.get("h", 0)))
        l = float(k.get("low", k.get("l", 0)))
        t = str(k.get("open_time", k.get("t", i)))
        
        bar = MergedBar(high=h, low=l, open_time=t, close_time=t, bar_count=1, index=i)
        
        if len(merged) < 2:
            merged.append(bar)
            continue
        
        prev = merged[-1]
        
        # 判断包含关系
        is_inclusive = (
            (prev.high >= bar.high and prev.low <= bar.low) or
            (bar.high >= prev.high and bar.low <= prev.low)
        )
        
        if is_inclusive:
            # 判断方向：看 merged[-2] 与 merged[-1] 的关系
            prev2 = merged[-2]
            going_up = prev.high > prev2.high
            
            if going_up:
                # 向上合并：取较高的 high 和较高的 low
                prev.high = max(prev.high, bar.high)
                prev.low = max(prev.low, bar.low)
            else:
                # 向下合并：取较低的 high 和较低的 low
                prev.high = min(prev.high, bar.high)
                prev.low = min(prev.low, bar.low)
            
            prev.bar_count += bar.bar_count
            prev.close_time = bar.close_time
        else:
            merged.append(bar)
    
    # 重新编号
    for i, b in enumerate(merged):
        b.index = i
    
    return merged


# ============================================================
# 2. 顶底分型识别
# ============================================================

def detect_fractals(merged_bars: List[MergedBar]) -> List[Fractal]:
    """
    识别顶底分型
    
    顶分型：中间 bar 的 high 是三者最高
      bars[i-1].high < bars[i].high AND bars[i].high > bars[i+1].high
    
    底分型：中间 bar 的 low 是三者最低
      bars[i-1].low > bars[i].low AND bars[i].low < bars[i+1].low
    """
    if len(merged_bars) < 3:
        return []
    
    fractals: List[Fractal] = []
    
    for i in range(1, len(merged_bars) - 1):
        prev = merged_bars[i - 1]
        curr = merged_bars[i]
        next_ = merged_bars[i + 1]
        
        # 顶分型
        if curr.high > prev.high and curr.high > next_.high:
            fractals.append(Fractal(
                type="top",
                price=curr.high,
                index=curr.index,
                bar_count=curr.bar_count,
                timestamp=curr.open_time,
            ))
        
        # 底分型
        elif curr.low < prev.low and curr.low < next_.low:
            fractals.append(Fractal(
                type="bottom",
                price=curr.low,
                index=curr.index,
                bar_count=curr.bar_count,
                timestamp=curr.open_time,
            ))
    
    return fractals


# ============================================================
# 3. 笔构建
# ============================================================

def build_strokes(fractals: List[Fractal], min_gap: int = 4) -> List[Stroke]:
    """
    构建笔：连接交替的顶底分型
    
    规则:
    - 顶→底 = 下降笔, 底→顶 = 上升笔
    - 相邻分型之间至少间隔 min_gap 根合并K线
    - 分型必须交替出现 (顶→底→顶→底)
    
    Args:
        fractals: 分型列表
        min_gap: 笔内最少合并K线数 (缠论标准 = 4)
    """
    if len(fractals) < 2:
        return []
    
    # 第一步：强制交替 — 连续同类分型中选极值
    alternating: List[Fractal] = [fractals[0]]
    
    for f in fractals[1:]:
        last = alternating[-1]
        if f.type == last.type:
            # 同类分型：顶取最高，底取最低
            if f.type == "top" and f.price > last.price:
                alternating[-1] = f
            elif f.type == "bottom" and f.price < last.price:
                alternating[-1] = f
        else:
            # 不同类型：检查间距
            if abs(f.index - last.index) >= min_gap:
                alternating.append(f)
            else:
                # 间距不足，用新的替换旧的（如果更极端）
                # 或跳过
                pass
    
    # 第二步：构建笔
    strokes: List[Stroke] = []
    
    for i in range(1, len(alternating)):
        f_start = alternating[i - 1]
        f_end = alternating[i]
        
        if f_start.type == "bottom" and f_end.type == "top":
            direction = "up"
        elif f_start.type == "top" and f_end.type == "bottom":
            direction = "down"
        else:
            continue  # 不合法
        
        strokes.append(Stroke(
            direction=direction,
            start_price=f_start.price,
            end_price=f_end.price,
            start_time=f_start.timestamp,
            end_time=f_end.timestamp,
            start_index=f_start.index,
            end_index=f_end.index,
            bar_span=abs(f_end.index - f_start.index),
        ))
    
    return strokes


# ============================================================
# 4. MACD 计算 + 背驰检测
# ============================================================

def _ema(data: List[float], period: int) -> List[float]:
    """指数移动平均"""
    if not data:
        return []
    
    result = [0.0] * len(data)
    multiplier = 2.0 / (period + 1)
    result[0] = data[0]
    
    for i in range(1, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    
    return result


def compute_macd(closes: List[float],
                 fast: int = 12,
                 slow: int = 26,
                 signal: int = 9) -> tuple:
    """
    计算 MACD
    
    Returns:
        (macd_line, signal_line, histogram) 三个列表
    """
    if len(closes) < slow + signal:
        return [], [], []
    
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    
    return macd_line, signal_line, histogram


def compute_macd_divergence(
    klines: List[dict],
    strokes: List[Stroke],
) -> DivergenceResult:
    """
    检测最近两个同向笔之间的 MACD 背驰
    
    方法：
    1. 计算全部 K 线的 MACD histogram
    2. 找最近两个下降笔（或上升笔）
    3. 对每个笔的区间求 histogram 绝对值之和 = "面积"
    4. 若最近笔面积 < 前一笔面积 → 背驰
    """
    if len(strokes) < 2:
        return DivergenceResult(detail="笔数不足，无法判断背驰")
    
    closes = [float(k.get("close", k.get("c", 0))) for k in klines]
    _, _, histogram = compute_macd(closes)
    
    if not histogram:
        return DivergenceResult(detail="K线不足，无法计算MACD")
    
    result = DivergenceResult()
    
    # 最近一笔
    last_stroke = strokes[-1]
    
    # 找同向的前一笔
    prev_same_dir = None
    for s in reversed(strokes[:-1]):
        if s.direction == last_stroke.direction:
            prev_same_dir = s
            break
    
    if not prev_same_dir:
        result.detail = "没有找到前一个同向笔"
        return result
    
    # 计算面积 (注意 index 对应原始 klines 的位置用 start_index/end_index)
    # 由于笔的 index 是合并 K 线的位置，我们需要将其映射回原始 K 线
    # 简化处理：直接用 index 作为近似位置
    def area_in_range(start_idx: int, end_idx: int) -> float:
        lo = max(0, start_idx)
        hi = min(len(histogram), end_idx + 1)
        return sum(abs(histogram[i]) for i in range(lo, hi))
    
    current_area = area_in_range(last_stroke.start_index, last_stroke.end_index)
    previous_area = area_in_range(prev_same_dir.start_index, prev_same_dir.end_index)
    
    ratio = current_area / previous_area if previous_area > 0 else 1.0
    
    result.current_area = round(current_area, 2)
    result.previous_area = round(previous_area, 2)
    result.area_ratio = round(ratio, 3)
    
    if last_stroke.direction == "up":
        # 上升笔：价格新高但面积缩小 → 顶背驰
        if last_stroke.end_price > prev_same_dir.end_price and ratio < 1.0:
            result.has_top_divergence = True
            result.detail = (
                f"顶背驰：上升笔价格{last_stroke.end_price:.2f}>"
                f"{prev_same_dir.end_price:.2f}, "
                f"但MACD面积{current_area:.1f}<{previous_area:.1f}, "
                f"萎缩{(1-ratio)*100:.1f}%"
            )
        else:
            result.detail = f"上升笔无背驰 (面积比={ratio:.2f})"
    else:
        # 下降笔：价格新低但面积缩小 → 底背驰
        if last_stroke.end_price < prev_same_dir.end_price and ratio < 1.0:
            result.has_bottom_divergence = True
            result.detail = (
                f"底背驰：下降笔价格{last_stroke.end_price:.2f}<"
                f"{prev_same_dir.end_price:.2f}, "
                f"但MACD面积{current_area:.1f}<{previous_area:.1f}, "
                f"萎缩{(1-ratio)*100:.1f}%"
            )
        else:
            result.detail = f"下降笔无背驰 (面积比={ratio:.2f})"
    
    return result


# ============================================================
# 5. 一键分析入口
# ============================================================

def analyze_chanlun(klines: List[dict]) -> dict:
    """
    一键缠论分析
    
    Args:
        klines: OHLCV K线列表，至少 50 根
                格式: [{"open_time", "open", "high", "low", "close", "volume"}, ...]
    
    Returns:
        结构化分析结果 dict，可直接序列化为 JSON 传给 AI
    """
    if len(klines) < 10:
        return {
            "error": f"K线数量不足 ({len(klines)} < 10)",
            "fractals": [],
            "strokes": [],
            "current_stroke": None,
            "macd_divergence": None,
            "summary": "数据不足，无法分析",
        }
    
    # 1. 包含处理
    merged = merge_inclusive_bars(klines)
    
    # 2. 分型识别
    fractals = detect_fractals(merged)
    
    # 3. 笔构建
    strokes = build_strokes(fractals)
    
    # 4. MACD 背驰检测
    divergence = compute_macd_divergence(klines, strokes)
    
    # 5. 当前进行中的笔
    current_stroke = None
    if fractals and klines:
        last_fractal = fractals[-1]
        last_close = float(klines[-1].get("close", klines[-1].get("c", 0)))
        last_time = str(klines[-1].get("open_time", klines[-1].get("t", "")))
        
        if last_fractal.type == "top":
            current_stroke = {
                "direction": "down",
                "start_price": last_fractal.price,
                "current_price": last_close,
                "start_time": last_fractal.timestamp,
                "current_time": last_time,
            }
        else:
            current_stroke = {
                "direction": "up",
                "start_price": last_fractal.price,
                "current_price": last_close,
                "start_time": last_fractal.timestamp,
                "current_time": last_time,
            }
    
    # 6. 趋势判定
    trend = "unknown"
    if len(fractals) >= 4:
        recent_tops = [f for f in fractals[-6:] if f.type == "top"]
        recent_bots = [f for f in fractals[-6:] if f.type == "bottom"]
        
        if len(recent_tops) >= 2 and len(recent_bots) >= 2:
            tops_rising = recent_tops[-1].price > recent_tops[-2].price
            bots_rising = recent_bots[-1].price > recent_bots[-2].price
            
            if tops_rising and bots_rising:
                trend = "up"
            elif not tops_rising and not bots_rising:
                trend = "down"
            else:
                trend = "consolidation"
    
    # 7. 生成摘要
    fractal_summary = ""
    if fractals:
        last_n = fractals[-4:] if len(fractals) >= 4 else fractals
        parts = []
        for f in last_n:
            emoji = "⬆️" if f.type == "top" else "⬇️"
            parts.append(f"{emoji}{f.price:.2f}")
        fractal_summary = "→".join(parts)
    
    summary_parts = [
        f"趋势: {trend}",
        f"分型数: {len(fractals)}",
        f"笔数: {len(strokes)}",
    ]
    if fractal_summary:
        summary_parts.append(f"最近分型: {fractal_summary}")
    if divergence.has_top_divergence:
        summary_parts.append("⚠️ 顶背驰信号")
    if divergence.has_bottom_divergence:
        summary_parts.append("⚠️ 底背驰信号")
    
    return {
        "trend": trend,
        "fractals": [
            {"type": f.type, "price": f.price, "time": f.timestamp, "index": f.index}
            for f in fractals[-8:]  # 最近 8 个分型
        ],
        "strokes": [
            {
                "direction": s.direction,
                "start_price": s.start_price,
                "end_price": s.end_price,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "bar_span": s.bar_span,
            }
            for s in strokes[-6:]  # 最近 6 笔
        ],
        "current_stroke": current_stroke,
        "macd_divergence": {
            "has_top_divergence": divergence.has_top_divergence,
            "has_bottom_divergence": divergence.has_bottom_divergence,
            "current_area": divergence.current_area,
            "previous_area": divergence.previous_area,
            "area_ratio": divergence.area_ratio,
            "detail": divergence.detail,
        },
        "summary": " | ".join(summary_parts),
    }
