"""
Market Data API
================
行情数据端点

提供 K 线数据查询接口，供前端图表和回测系统使用。
"""

from typing import Optional
from decimal import Decimal
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc

from app.api.deps import DbSession
from app.models.market import Kline


router = APIRouter()


# ==================== Schemas ====================

class KlineResponse(BaseModel):
    """K 线数据响应"""
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    class Config:
        from_attributes = True


class KlineListResponse(BaseModel):
    """K 线列表响应"""
    symbol: str
    interval: str
    count: int
    data: list[KlineResponse]


# ==================== Routes ====================

@router.get("/klines", response_model=KlineListResponse)
async def get_klines(
    db: DbSession,
    symbol: str = Query(default="BTCUSDT", description="交易对"),
    interval: str = Query(default="1m", description="时间周期"),
    limit: int = Query(default=100, ge=1, le=10000, description="返回数量"),
):
    """
    获取 K 线数据
    
    按 open_time 倒序取最新 N 条，然后反转为正序返回（便于前端绘图）。
    支持 Redis 缓存加速（cache-aside 模式）。
    
    Parameters:
    - symbol: 交易对 (如 BTCUSDT)
    - interval: 时间周期 (1m, 5m, 15m, 30m, 1h, 4h, 1d)
    - limit: 返回数量 (1-10000)
    
    Returns:
    - 按时间正序排列的 K 线数据
    """
    from app.services.kline_cache import kline_cache
    
    # 1. 尝试从 Redis 缓存获取
    cached = await kline_cache.get(symbol, interval, limit)
    if cached:
        return KlineListResponse(**cached)
    
    # 2. 缓存未命中 → 查询数据库
    query = (
        select(Kline)
        .where(Kline.symbol == symbol)
        .where(Kline.interval == interval)
        .order_by(desc(Kline.open_time))
        .limit(limit)
    )
    
    result = await db.execute(query)
    klines = result.scalars().all()
    
    # 反转为正序 (时间从早到晚)
    klines = list(reversed(klines))
    
    # 转换为响应格式
    data = [
        KlineResponse(
            symbol=k.symbol,
            interval=k.interval,
            open_time=k.open_time,
            open=float(k.open),
            high=float(k.high),
            low=float(k.low),
            close=float(k.close),
            volume=float(k.volume),
        )
        for k in klines
    ]
    
    response = KlineListResponse(
        symbol=symbol,
        interval=interval,
        count=len(data),
        data=data,
    )
    
    # 3. 写入缓存 (异步，不阻塞响应)
    await kline_cache.set(symbol, interval, limit, response.model_dump())
    
    return response


@router.get("/klines/latest", response_model=KlineResponse)
async def get_latest_kline(
    db: DbSession,
    symbol: str = Query(default="BTCUSDT", description="交易对"),
    interval: str = Query(default="1m", description="时间周期"),
):
    """
    获取最新一根 K 线
    
    用于前端实时价格显示。
    """
    query = (
        select(Kline)
        .where(Kline.symbol == symbol)
        .where(Kline.interval == interval)
        .order_by(desc(Kline.open_time))
        .limit(1)
    )
    
    result = await db.execute(query)
    kline = result.scalar_one_or_none()
    
    if not kline:
        raise HTTPException(
            status_code=404, 
            detail=f"No kline data for {symbol} {interval}"
        )
    
    return KlineResponse(
        symbol=kline.symbol,
        interval=kline.interval,
        open_time=kline.open_time,
        open=float(kline.open),
        high=float(kline.high),
        low=float(kline.low),
        close=float(kline.close),
        volume=float(kline.volume),
    )


@router.get("/symbols")
async def get_symbols(db: DbSession):
    """
    获取所有可用交易对
    
    返回数据库中存在的所有交易对列表。
    """
    query = select(Kline.symbol).distinct()
    result = await db.execute(query)
    symbols = [row[0] for row in result.fetchall()]
    
    return {"symbols": symbols}


@router.get("/intervals")
async def get_intervals():
    """
    获取支持的时间周期
    """
    return {
        "intervals": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    }


@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str, db: DbSession):
    """
    获取实时行情 (直接从币安获取, 失败时从数据库获取)
    
    用于前端实时价格显示，比 K 线数据更准确。
    
    Returns:
    - symbol: 交易对
    - price: 最新价格
    - change_percent: 24h 涨跌幅
    - high_24h: 24h 最高价
    - low_24h: 24h 最低价
    - volume: 24h 成交量
    """
    from app.services.exchange import BinanceClient
    
    client = BinanceClient()
    ticker = await client.get_ticker(symbol.upper())
    
    if ticker:
        return {
            "symbol": ticker.get("symbol", symbol.upper()),
            "price": float(ticker.get("lastPrice", 0)),
            "change_percent": float(ticker.get("priceChangePercent", 0)),
            "high_24h": float(ticker.get("highPrice", 0)),
            "low_24h": float(ticker.get("lowPrice", 0)),
            "volume": float(ticker.get("volume", 0)),
        }
    
    # Fallback: 从数据库获取最新 K 线收盘价
    query = (
        select(Kline)
        .where(Kline.symbol == symbol.upper())
        .order_by(desc(Kline.open_time))
        .limit(1)
    )
    result = await db.execute(query)
    kline = result.scalar_one_or_none()
    
    if kline:
        return {
            "symbol": symbol.upper(),
            "price": float(kline.close),
            "change_percent": 0.0,  # 无法从单条K线计算
            "high_24h": float(kline.high),
            "low_24h": float(kline.low),
            "volume": float(kline.volume),
            "source": "database",  # 标记数据来源
        }
    
    # 最后 fallback: 返回 0 而不是 503
    raise HTTPException(
        status_code=503,
        detail=f"Unable to fetch ticker for {symbol} (no data in database either)"
    )
