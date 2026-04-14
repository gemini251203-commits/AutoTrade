"""
行情工具 — get_price, get_funding_rate, get_klines
"""

import json
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.market import Kline
from ._registry import register_tool


@register_tool
async def get_price(db: AsyncSession, user_id: int, symbol: str = "BTCUSDT") -> str:
    """查询实时价格"""
    try:
        from app.services.exchange import BinanceClient
        client = BinanceClient()
        ticker = await client.get_ticker(symbol.upper())
        if ticker:
            return json.dumps({
                "symbol": ticker.get("symbol", symbol.upper()),
                "price": float(ticker.get("lastPrice", 0)),
                "change_24h": f"{float(ticker.get('priceChangePercent', 0)):+.2f}%",
                "high_24h": float(ticker.get("highPrice", 0)),
                "low_24h": float(ticker.get("lowPrice", 0)),
                "volume_24h": float(ticker.get("volume", 0)),
            }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"[AgentTools] get_price failed: {e}")

    # Fallback: 从数据库获取
    result = await db.execute(
        select(Kline)
        .where(Kline.symbol == symbol.upper())
        .order_by(desc(Kline.open_time))
        .limit(1)
    )
    kline = result.scalar_one_or_none()
    if kline:
        return json.dumps({
            "symbol": symbol.upper(),
            "price": float(kline.close),
            "source": "database",
        }, ensure_ascii=False, default=str)

    return json.dumps({"error": f"无法获取 {symbol} 价格"}, ensure_ascii=False, default=str)


@register_tool
async def get_funding_rate(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """
    查询资金费率 — 交易成本分析

    参数:
        symbol: 交易对, 如 BTCUSDT / ETHUSDT

    返回:
        当前费率、年化成本、下次结算时间、多空方向提示
    """
    from app.services.funding_rate import funding_rate_service
    info = await funding_rate_service.get_funding_info(symbol.upper())
    if info:
        return json.dumps(info, ensure_ascii=False, default=str)

    return json.dumps({"error": f"无法获取 {symbol} 资金费率"}, ensure_ascii=False, default=str)

@register_tool
async def get_klines(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 20,
) -> str:
    """获取 K 线数据"""
    limit = min(int(limit), 50)  # 限制返回数量避免 token 过多
    result = await db.execute(
        select(Kline)
        .where(Kline.symbol == symbol.upper(), Kline.interval == interval)
        .order_by(desc(Kline.open_time))
        .limit(limit)
    )
    klines = list(reversed(result.scalars().all()))

    if not klines:
        return json.dumps({"error": f"无 {symbol} {interval} K线数据"}, ensure_ascii=False, default=str)

    data = [
        {
            "open_time": k.open_time,
            "open": float(k.open),
            "high": float(k.high),
            "low": float(k.low),
            "close": float(k.close),
            "volume": float(k.volume),
        }
        for k in klines
    ]
    return json.dumps({
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(data),
        "data": data,
    }, ensure_ascii=False, default=str)
