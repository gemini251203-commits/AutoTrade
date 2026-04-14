"""
分析工具 — get_indicators, analyze_market, query_memories
"""

import json
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.strategy import TradeMemory
from ._registry import register_tool


@register_tool
async def get_indicators(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
) -> str:
    """获取技术指标 (增强版 — 使用完整指标库)"""
    from app.core.network import net_manager
    from app.services.quant.indicators import calculate_all_indicators

    try:
        async with net_manager.get_client(timeout=15.0) as client:
            resp = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "limit": 200,
                },
            )
            if resp.status_code == 200:
                raw = resp.json()
                if raw and len(raw) >= 50:
                    # 转换为 indicators.py 要求的 kline dict 格式
                    klines = []
                    for k in raw:
                        klines.append({
                            "open_time": k[0],
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": k[6],
                            "quote_volume": float(k[7]),
                        })

                    # 调用完整指标计算
                    indicators = calculate_all_indicators(klines)

                    # 格式化输出 — 只保留关键数据，避免过长
                    result = {
                        "symbol": symbol.upper(),
                        "interval": interval,
                        "current_price": indicators["price"]["close"],
                        "rsi": indicators.get("rsi"),
                        "macd": indicators.get("macd"),
                        "bollinger": indicators.get("bollinger"),
                        "kdj": indicators.get("kdj"),
                        "atr": indicators.get("atr"),
                        "volume_ratio": indicators.get("volume_ratio"),
                        "volume_surge": indicators.get("volume_surge"),
                        "support_resistance": {
                            "nearest_support": indicators.get("support_resistance", {}).get("nearest_support"),
                            "nearest_resistance": indicators.get("support_resistance", {}).get("nearest_resistance"),
                        },
                        "ema": indicators.get("ema"),
                        "vegas_tunnel": {
                            "ema_144": (indicators.get("ema") or {}).get("ema_144"),
                            "ema_169": (indicators.get("ema") or {}).get("ema_169"),
                        },
                        "patterns": {k: v for k, v in (indicators.get("patterns") or {}).items() if v},
                    }

                    # 判断趋势
                    rsi = result.get("rsi")
                    ema = result.get("ema") or {}
                    price = result["current_price"]
                    ema20 = ema.get("ema_20")
                    ema50 = ema.get("ema_50")
                    trend = "neutral"
                    if rsi and ema20 and ema50:
                        if rsi > 50 and price > ema20 > ema50:
                            trend = "bullish"
                        elif rsi < 50 and price < ema20 < ema50:
                            trend = "bearish"
                    result["trend"] = trend

                    return json.dumps(result, ensure_ascii=False, default=str)
            else:
                logger.warning(f"[AgentTools] Binance klines HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"[AgentTools] get_indicators failed: {e}")

    return json.dumps({"error": f"无法获取 {symbol} {interval} 指标"}, ensure_ascii=False, default=str)


@register_tool
async def analyze_market(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """综合市场分析 (调用多智能体)"""
    try:
        from app.services.ai.brain import AIBrain
        brain = AIBrain()
        result = await brain.multi_analyze(db=db, user_id=user_id, symbol=symbol.upper())

        return json.dumps({
            "symbol": symbol.upper(),
            "analysis": result,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"[AgentTools] analyze_market failed: {e}")
        return json.dumps({"error": f"市场分析失败: {str(e)}"}, ensure_ascii=False, default=str)


@register_tool
async def query_memories(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """查询交易记忆 (所有来源: 手动/AI/信号/量化)"""
    result = await db.execute(
        select(TradeMemory)
        .where(
            TradeMemory.user_id == user_id,
            TradeMemory.symbol == symbol.upper(),
        )
        .order_by(desc(TradeMemory.created_at))
        .limit(10)
    )
    memories = result.scalars().all()

    if not memories:
        return json.dumps({
            "memories": [],
            "message": f"暂无 {symbol} 的交易记忆",
        }, ensure_ascii=False, default=str)

    source_labels = {
        "manual": "手动", "agent": "AI Agent", "hub": "AI Hub",
        "signal": "信号助手", "quant": "量化策略",
    }

    data = [
        {
            "symbol": m.symbol,
            "source": source_labels.get(m.source, m.source) if m.source else "未知",
            "side": m.side,
            "entry_price": m.entry_price,
            "exit_price": m.exit_price,
            "leverage": m.leverage,
            "trade_result": m.trade_result,
            "pnl_pct": m.pnl_pct,
            "pnl_usdt": m.pnl_usdt,
            "duration_min": m.duration_minutes,
            "close_reason": m.close_reason,
            "had_stop_loss": m.had_stop_loss,
            "had_take_profit": m.had_take_profit,
            "open_reason": m.open_reason,
            "lesson": m.lesson,
            "created_at": m.created_at.isoformat() + "Z" if m.created_at else "",
        }
        for m in memories
    ]
    return json.dumps({"memories": data, "total": len(data)}, ensure_ascii=False, default=str)
