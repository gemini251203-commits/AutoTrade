"""
Tool Result Compressor — 工具结果压缩器
==========================================
对高频工具的 JSON 返回结果做摘要，保留 AI 决策需要的关键字段，
删除冗余信息，减少 messages 中的 token 消耗。

压缩策略:
- get_price: 只保留 symbol/price/change_24h
- get_indicators: 只保留 rsi/macd/trend/price，删除 ema 全序列
- get_balance: 只保留 available/margin_used/open_positions
- get_positions: 精简每个持仓的关键字段
- get_funding_rate: 只保留费率和方向
- manage_grid: 精简网格状态
- get_klines: 大幅压缩 K 线数据
"""

import json
from typing import Optional
from loguru import logger


# 需要压缩的工具名 → 压缩函数映射
_COMPRESSORS = {}


def _register(name: str):
    """注册压缩器"""
    def decorator(func):
        _COMPRESSORS[name] = func
        return func
    return decorator


def compress_tool_result(tool_name: str, raw_result: str) -> str:
    """
    压缩工具返回结果
    
    Args:
        tool_name: 工具名称
        raw_result: 原始 JSON 字符串
    
    Returns:
        压缩后的 JSON 字符串 (如果无对应压缩器则原样返回)
    """
    compressor = _COMPRESSORS.get(tool_name)
    if not compressor:
        return raw_result
    
    try:
        data = json.loads(raw_result)
        # 如果是错误返回，不压缩
        if isinstance(data, dict) and "error" in data:
            return raw_result
        
        compressed = compressor(data)
        result = json.dumps(compressed, ensure_ascii=False, default=str)
        
        saved = len(raw_result) - len(result)
        if saved > 50:
            logger.debug(
                f"[Compressor] {tool_name}: {len(raw_result)} → {len(result)} chars "
                f"(saved {saved}, {saved * 100 // len(raw_result)}%)"
            )
        return result
    except Exception as e:
        logger.debug(f"[Compressor] {tool_name} compression failed: {e}")
        return raw_result


# ==================== 压缩器实现 ====================


@_register("get_price")
def _compress_price(data: dict) -> dict:
    """价格: 只保留核心字段"""
    return {
        "symbol": data.get("symbol"),
        "price": data.get("price"),
        "change_24h": data.get("change_24h"),
    }


@_register("get_indicators")
def _compress_indicators(data: dict) -> dict:
    """技术指标: 大幅精简，只保留决策关键数据"""
    result = {
        "symbol": data.get("symbol"),
        "interval": data.get("interval"),
        "price": data.get("current_price"),
        "rsi": data.get("rsi"),
        "trend": data.get("trend"),
    }
    
    # MACD: 只保留方向信号
    macd = data.get("macd")
    if isinstance(macd, dict):
        result["macd"] = {
            "histogram": macd.get("macd_histogram"),
            "golden_cross": macd.get("macd_golden_cross"),
            "death_cross": macd.get("macd_death_cross"),
        }
    
    # 布林带: 只保留上下轨和宽度
    boll = data.get("bollinger")
    if isinstance(boll, dict):
        result["bollinger"] = {
            "upper": boll.get("upper"),
            "lower": boll.get("lower"),
            "width": boll.get("width"),
        }
    
    # 支撑阻力: 保留
    sr = data.get("support_resistance")
    if sr:
        result["support_resistance"] = sr
    
    # K线形态: 只保留有信号的
    patterns = data.get("patterns")
    if isinstance(patterns, dict):
        active = {k: v for k, v in patterns.items() if v}
        if active:
            result["patterns"] = active
    
    # ATR: 保留
    if data.get("atr"):
        result["atr"] = data["atr"]
    
    # EMA: 只保留关键均线
    ema = data.get("ema")
    if isinstance(ema, dict):
        result["ema_summary"] = {
            k: v for k, v in ema.items()
            if k in ("ema_20", "ema_50", "ema_200") and v is not None
        }
    
    return result


@_register("get_balance")
def _compress_balance(data: dict) -> dict:
    """余额: 删除 note 等冗余字段"""
    return {
        "available": data.get("available"),
        "frozen": data.get("frozen"),
        "total_equity": data.get("total_equity"),
        "margin_used": data.get("margin_used"),
        "open_positions": data.get("open_positions"),
    }


@_register("get_positions")
def _compress_positions(data: dict) -> dict:
    """持仓: 精简每个持仓，删除冗余说明"""
    positions = data.get("positions", [])
    if not positions:
        return {"positions": [], "count": 0}
    
    compressed = []
    for p in positions:
        compressed.append({
            "id": p.get("id"),
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "size": p.get("size"),
            "entry": p.get("entry_price"),
            "lev": p.get("leverage"),
            "margin": p.get("margin"),
            "pnl": p.get("unrealized_pnl"),
            "sl": p.get("stop_loss"),
            "tp": p.get("take_profit"),
        })
    
    summary = data.get("summary", {})
    return {
        "positions": compressed,
        "total_margin": summary.get("total_margin_used"),
        "total_pnl": summary.get("total_unrealized_pnl"),
    }


@_register("get_funding_rate")
def _compress_funding_rate(data: dict) -> dict:
    """资金费率: 只留核心费率信息"""
    return {
        "symbol": data.get("symbol"),
        "rate": data.get("rate"),
        "rate_pct": data.get("rate_percent"),
        "annualized": data.get("annualized_rate"),
        "direction": data.get("direction_hint"),
        "next_settle": data.get("next_funding_time"),
    }


@_register("get_klines")
def _compress_klines(data: dict) -> dict:
    """K线: 只保留最近5根的 OHLCV"""
    klines = data.get("data", [])
    if not klines:
        return data
    
    # 只保留最近 5 根
    recent = klines[-5:]
    compressed = []
    for k in recent:
        compressed.append({
            "c": k.get("close"),
            "h": k.get("high"),
            "l": k.get("low"),
            "v": round(k.get("volume", 0), 1),
        })
    
    return {
        "symbol": data.get("symbol"),
        "interval": data.get("interval"),
        "count": len(klines),
        "recent_5": compressed,
    }


@_register("manage_grid")
def _compress_grid(data: dict) -> dict:
    """网格: 精简网格列表"""
    # manage_grid 的返回格式可能多样，做安全处理
    if isinstance(data, dict):
        grids = data.get("grids", data.get("data", []))
        if isinstance(grids, list) and grids:
            compressed = []
            for g in grids:
                if isinstance(g, dict):
                    compressed.append({
                        "id": g.get("id"),
                        "symbol": g.get("symbol"),
                        "status": g.get("status"),
                        "pnl": g.get("total_pnl") or g.get("realized_pnl"),
                        "range": f"{g.get('lower_price')}-{g.get('upper_price')}",
                    })
            if compressed:
                return {"grids": compressed, "count": len(compressed)}
    return data


@_register("get_open_orders")
def _compress_orders(data: dict) -> dict:
    """挂单: 精简字段"""
    orders = data.get("orders", [])
    if not orders:
        return data
    
    compressed = []
    for o in orders:
        compressed.append({
            "id": o.get("id"),
            "symbol": o.get("symbol"),
            "side": o.get("side"),
            "type": o.get("order_type"),
            "qty": o.get("quantity"),
            "price": o.get("price"),
        })
    return {"orders": compressed}
