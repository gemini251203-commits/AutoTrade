"""
趋势分析工具 — analyze_trend, analyze_trend_now, get_trend_result
"""

import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.time_utils import utc_now
from ._registry import register_tool


@register_tool
async def analyze_trend(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """
    多周期趋势分析 — 分别在 15m/1h/4h/1d 四个周期判断趋势

    并推荐适合当前趋势的策略类型
    """
    from app.core.network import net_manager
    from app.services.quant.indicators import (
        calculate_rsi, calculate_ema, calculate_macd,
        calculate_bollinger, calculate_atr,
    )

    timeframes = ["15m", "1h", "4h", "1d"]
    trends = {}

    for tf in timeframes:
        try:
            async with net_manager.get_client(timeout=15.0) as client:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={
                        "symbol": symbol.upper(),
                        "interval": tf,
                        "limit": 100,
                    },
                )
                if resp.status_code != 200:
                    trends[tf] = {"trend": "unknown", "error": f"HTTP {resp.status_code}"}
                    continue
                raw = resp.json()
        except Exception as e:
            trends[tf] = {"trend": "unknown", "error": str(e)}
            continue

        if not raw or len(raw) < 30:
            trends[tf] = {"trend": "unknown", "error": "数据不足"}
            continue

        closes = [float(k[4]) for k in raw]
        klines_data = [{
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
            "volume": float(k[5]),
        } for k in raw]

        rsi = calculate_rsi(closes)
        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)
        macd = calculate_macd(closes)
        atr = calculate_atr(klines_data)
        price = closes[-1]

        # 判断趋势
        trend = "neutral"
        signals = []

        if ema20 and ema50:
            if price > ema20 > ema50:
                signals.append("bullish")
            elif price < ema20 < ema50:
                signals.append("bearish")
            else:
                signals.append("neutral")

        if rsi:
            if rsi > 60:
                signals.append("bullish")
            elif rsi < 40:
                signals.append("bearish")
            else:
                signals.append("neutral")

        if macd:
            if macd["histogram"] and macd["histogram"] > 0:
                signals.append("bullish")
            elif macd["histogram"] and macd["histogram"] < 0:
                signals.append("bearish")
            else:
                signals.append("neutral")

        bullish = signals.count("bullish")
        bearish = signals.count("bearish")
        if bullish >= 2:
            trend = "bullish"
        elif bearish >= 2:
            trend = "bearish"
        else:
            trend = "neutral"

        trends[tf] = {
            "trend": trend,
            "price": round(price, 2),
            "rsi": round(rsi, 1) if rsi else None,
            "ema_20": round(ema20, 2) if ema20 else None,
            "ema_50": round(ema50, 2) if ema50 else None,
            "macd_histogram": round(macd["histogram"], 4) if macd and macd.get("histogram") else None,
            "atr": round(atr, 2) if atr else None,
        }

    # 综合判断
    macro_trends = [trends.get(tf, {}).get("trend", "unknown") for tf in ["4h", "1d"]]
    micro_trends = [trends.get(tf, {}).get("trend", "unknown") for tf in ["15m", "1h"]]

    macro = "bullish" if macro_trends.count("bullish") >= 1 else \
            "bearish" if macro_trends.count("bearish") >= 1 else "neutral"
    micro = "bullish" if micro_trends.count("bullish") >= 1 else \
            "bearish" if micro_trends.count("bearish") >= 1 else "neutral"

    # 策略推荐
    recommendations = []
    if macro == "bullish" and micro == "bullish":
        recommendations = ["趋势跟踪策略 (顺势做多)", "均线金叉策略", "RSI 回调买入"]
    elif macro == "bearish" and micro == "bearish":
        recommendations = ["趋势跟踪策略 (顺势做空)", "RSI 超买做空", "均线死叉策略"]
    elif macro == "bullish" and micro in ["neutral", "bearish"]:
        recommendations = ["逢低买入策略", "RSI 超卖反弹 (大趋势看涨，短期回调)", "支撑位反弹"]
    elif macro == "bearish" and micro in ["neutral", "bullish"]:
        recommendations = ["逢高做空策略", "阻力位反弹做空 (大趋势看跌，短期反弹)"]
    else:
        recommendations = ["区间震荡策略", "布林带突破", "等待趋势明确再入场"]

    return json.dumps({
        "symbol": symbol.upper(),
        "macro_trend": macro,
        "micro_trend": micro,
        "timeframes": trends,
        "recommendations": recommendations,
    }, ensure_ascii=False, default=str)


@register_tool
async def analyze_trend_now(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
):
    """
    用活跃趋势方案分析当前市场趋势

    参数:
        symbol: 交易对 (默认 BTCUSDT)

    返回:
        趋势方向、强度、波动率、动量、市场体制、适合的策略类型
    """
    from app.models.trend_scheme import TrendScheme
    from app.services.quant.trend_analyzer import TrendAnalyzer

    try:
        # 获取活跃方案
        result = await db.execute(
            select(TrendScheme).where(
                TrendScheme.user_id == user_id,
                TrendScheme.is_active == True,
            ).limit(1)
        )
        scheme = result.scalar_one_or_none()

        if not scheme:
            return json.dumps({"error": "没有活跃的趋势分析方案，请先创建或初始化预置方案"}, ensure_ascii=False, default=str)

        # 获取 K 线
        from app.core.network import net_manager
        analyzer = TrendAnalyzer()
        config = analyzer.parse_yaml(scheme.config_yaml)
        interval = config.get("interval", "1h")

        async with net_manager.get_client(timeout=15.0) as client:
            resp = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={"symbol": symbol.upper(), "interval": interval, "limit": 200},
            )
            if resp.status_code != 200:
                return json.dumps({"error": "获取行情失败"}, ensure_ascii=False, default=str)

            raw = resp.json()
            klines = [{
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            } for k in raw]

        # 分析
        trend_result = analyzer.analyze(config, klines, symbol=symbol.upper())

        # 缓存结果
        scheme.last_result = trend_result.to_dict()
        scheme.last_run_at = utc_now()
        await db.commit()

        return json.dumps({
            "scheme": scheme.name,
            "symbol": symbol.upper(),
            "direction": trend_result.direction,
            "direction_score": trend_result.direction_score,
            "strength": trend_result.strength,
            "volatility": trend_result.volatility,
            "momentum": trend_result.momentum,
            "regime": trend_result.regime,
            "confidence": trend_result.confidence,
            "suitable": trend_result.suitable_strategies,
            "unsuitable": trend_result.unsuitable_strategies,
            "summary": trend_result.summary(),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


@register_tool
async def get_trend_result(
    db: AsyncSession,
    user_id: int,
    symbol: str = "",
):
    """
    获取最近的趋势分析结果 (不重新分析，读取缓存)

    参数:
        symbol: 可选，过滤交易对

    返回:
        所有活跃方案的最近分析结果
    """
    from app.models.trend_scheme import TrendScheme

    try:
        result = await db.execute(
            select(TrendScheme).where(
                TrendScheme.user_id == user_id,
                TrendScheme.is_active == True,
            )
        )
        schemes = result.scalars().all()

        if not schemes:
            return json.dumps({"error": "没有活跃的趋势分析方案"}, ensure_ascii=False, default=str)

        results = []
        for s in schemes:
            if s.last_result:
                r = s.last_result
                if symbol and r.get("symbol", "") != symbol.upper():
                    continue
                results.append({
                    "scheme": s.name,
                    "symbol": r.get("symbol", ""),
                    "direction": r.get("direction", "unknown"),
                    "strength": r.get("strength", "unknown"),
                    "volatility": r.get("volatility", "unknown"),
                    "momentum": r.get("momentum", "unknown"),
                    "regime": r.get("regime", "unknown"),
                    "suitable": r.get("suitable_strategies", []),
                    "last_run": s.last_run_at.isoformat() + "Z" if s.last_run_at else None,
                })

        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)
