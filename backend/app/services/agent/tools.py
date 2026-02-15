"""
Agent Tools
=============
AI 交易代理的工具集

每个工具是一个 async 函数，调用现有后端服务完成实际操作。
工具的输入输出都是简单的 dict/str，方便 AI 解析。

命名规范:
- 工具名: snake_case (与 prompts.py 中的工具名一一对应)
- 参数名: snake_case (与 API 层/DB 层一致)
"""

import json
from typing import Optional, Dict, Any
from decimal import Decimal

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.order import Order, OrderSide, OrderType, OrderStatus
from app.models.position import Position, PositionSide, PositionStatus, MarginMode
from app.models.wallet import Wallet
from app.models.market import Kline
from app.models.strategy import TradeMemory


# ==================== 工具注册表 ====================

TOOL_REGISTRY: Dict[str, Any] = {}


def register_tool(func):
    """注册工具到全局注册表"""
    TOOL_REGISTRY[func.__name__] = func
    return func


# ==================== 行情工具 ====================

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
            }, ensure_ascii=False)
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
        }, ensure_ascii=False)

    return json.dumps({"error": f"无法获取 {symbol} 价格"}, ensure_ascii=False)


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
        return json.dumps({"error": f"无 {symbol} {interval} K线数据"}, ensure_ascii=False)

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
    }, ensure_ascii=False)


# ==================== 账户工具 ====================

@register_tool
async def get_balance(db: AsyncSession, user_id: int) -> str:
    """查询账户余额"""
    result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        return json.dumps({"error": "钱包未初始化"}, ensure_ascii=False)

    return json.dumps({
        "available": float(wallet.balance),
        "frozen": float(wallet.frozen),
        "total_equity": float(wallet.total_equity),
        "total_pnl": float(wallet.total_pnl),
    }, ensure_ascii=False)


@register_tool
async def get_positions(db: AsyncSession, user_id: int) -> str:
    """查询当前持仓"""
    result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    positions = result.scalars().all()

    if not positions:
        return json.dumps({"positions": [], "message": "当前无持仓"}, ensure_ascii=False)

    data = [
        {
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side.value,
            "size": float(p.size),
            "entry_price": float(p.entry_price),
            "leverage": p.leverage,
            "margin": float(p.margin),
            "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl else 0,
            "stop_loss": float(p.stop_loss) if p.stop_loss else None,
            "take_profit": float(p.take_profit) if p.take_profit else None,
        }
        for p in positions
    ]
    return json.dumps({"positions": data}, ensure_ascii=False)


@register_tool
async def get_open_orders(db: AsyncSession, user_id: int) -> str:
    """查询挂单"""
    result = await db.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
        )
    )
    orders = result.scalars().all()

    if not orders:
        return json.dumps({"orders": [], "message": "当前无挂单"}, ensure_ascii=False)

    data = [
        {
            "id": o.id,
            "symbol": o.symbol,
            "side": o.side.value,
            "order_type": o.order_type.value,
            "quantity": float(o.quantity),
            "price": float(o.price) if o.price else None,
            "status": o.status.value,
            "leverage": o.leverage,
        }
        for o in orders
    ]
    return json.dumps({"orders": data}, ensure_ascii=False)

# ==================== 交易工具 ====================

# Binance 合约最小名义价值 (USDT)
MIN_NOTIONAL = {
    "BTCUSDT": 100,
    "ETHUSDT": 20,
    "BNBUSDT": 20,
    "SOLUSDT": 5,
    "DOGEUSDT": 5,
    "XRPUSDT": 5,
    "ADAUSDT": 5,
    "AVAXUSDT": 5,
    "DOTUSDT": 5,
    "LINKUSDT": 5,
    "MATICUSDT": 5,
    "NEARUSDT": 5,
    "FTMUSDT": 5,
    "ATOMUSDT": 5,
    "OPUSDT": 5,
    "ARBUSDT": 5,
    "PEPEUSDT": 5,
    "SHIBUSDT": 5,
    "WIFUSDT": 5,
    "SUIUSDT": 5,
}
DEFAULT_MIN_NOTIONAL = 5  # 其他币种默认

# 数量精度 (最小下单步长)
QUANTITY_PRECISION = {
    "BTCUSDT": 3,    # 0.001
    "ETHUSDT": 2,    # 0.01
    "BNBUSDT": 2,    # 0.01
    "SOLUSDT": 1,    # 0.1
    "DOGEUSDT": 0,   # 1
    "XRPUSDT": 1,    # 0.1
}
DEFAULT_QTY_PRECISION = 2  # 0.01


@register_tool
async def place_order(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    order_type: str = "market",
    quantity: float = 0.01,
    leverage: int = 1,
    price: float = 0,
) -> str:
    """下单 (含 Binance 规则预检验)"""
    from app.services.trading import OrderExecutor, OrderError

    try:
        symbol = symbol.upper()

        # ==================== 预检验: Binance 最小名义价值 ====================
        # 获取实时价格用于计算名义价值
        from app.services.exchange import BinanceClient
        client = BinanceClient()
        try:
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker.get("lastPrice", 0)) if ticker else 0
        except Exception:
            current_price = 0

        if current_price > 0:
            notional = quantity * current_price  # 名义价值
            min_notional = MIN_NOTIONAL.get(symbol, DEFAULT_MIN_NOTIONAL)
            margin = notional / leverage if leverage > 0 else notional

            if notional < min_notional:
                # 计算建议: 满足最小名义所需的最小数量
                qty_precision = QUANTITY_PRECISION.get(symbol, DEFAULT_QTY_PRECISION)
                min_qty = min_notional / current_price
                # 向上取整到精度
                import math
                factor = 10 ** qty_precision
                suggested_qty = math.ceil(min_qty * factor) / factor
                suggested_margin = (suggested_qty * current_price) / leverage

                return json.dumps({
                    "success": False,
                    "error": (
                        f"名义价值不足: {quantity} × ${current_price:,.2f} = ${notional:,.2f}, "
                        f"但 {symbol} 最小名义为 ${min_notional}。\n"
                        f"建议: quantity={suggested_qty} (名义=${suggested_qty * current_price:,.2f}), "
                        f"保证金约 ${suggested_margin:,.2f} ({leverage}x杠杆)。\n"
                        f"或者提高杠杆 / 选择最小名义更低的币种 (如 SOLUSDT: $5)"
                    ),
                    "suggestion": {
                        "symbol": symbol,
                        "min_quantity": suggested_qty,
                        "min_notional": min_notional,
                        "suggested_margin": round(suggested_margin, 2),
                        "current_price": current_price,
                    }
                }, ensure_ascii=False)

            # 检查保证金是否够
            wallet_result = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallet = wallet_result.scalar_one_or_none()
            if wallet and margin > float(wallet.balance):
                return json.dumps({
                    "success": False, 
                    "error": (
                        f"保证金不足: 需要 ${margin:,.2f} (名义${notional:,.2f} / {leverage}x), "
                        f"但可用余额仅 ${float(wallet.balance):,.2f}。\n"
                        f"建议提高杠杆或减少数量。"
                    )
                }, ensure_ascii=False)

        # ==================== 通过预检验, 执行下单 ====================
        order_side = OrderSide(side.lower())
        otype = OrderType(order_type.lower())
        order_price = Decimal(str(price)) if price and float(price) > 0 else None

        order = await OrderExecutor.create_order(
            db=db,
            user_id=user_id,
            symbol=symbol,
            side=order_side,
            order_type=otype,
            quantity=Decimal(str(quantity)),
            price=order_price,
            leverage=int(leverage),
        )

        return json.dumps({
            "success": True,
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "quantity": float(order.quantity),
            "leverage": order.leverage,
            "status": order.status.value,
            "avg_fill_price": float(order.avg_fill_price) if order.avg_fill_price else None,
            "message": f"{'市价' if otype == OrderType.MARKET else '限价'}单已{'成交' if order.status == OrderStatus.FILLED else '挂出'}",
        }, ensure_ascii=False)

    except OrderError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[AgentTools] place_order failed: {e}")
        return json.dumps({"success": False, "error": f"下单失败: {str(e)}"}, ensure_ascii=False)


@register_tool
async def close_position(
    db: AsyncSession,
    user_id: int,
    position_id: int = 0,
    close_price: float = 0,
) -> str:
    """平仓"""
    from app.services.trading import PositionManager, PositionError

    try:
        # PositionManager.close_position 是 @staticmethod
        # 签名: (db, position_id, close_price, close_quantity=None)
        # 返回: (position, realized_pnl)
        position, realized_pnl = await PositionManager.close_position(
            db=db,
            position_id=int(position_id),
            close_price=Decimal(str(close_price)),
        )

        return json.dumps({
            "success": True,
            "position_id": position.id,
            "symbol": position.symbol,
            "realized_pnl": float(realized_pnl),
            "message": f"仓位 #{position.id} 已平仓，盈亏 {float(realized_pnl):+.2f} USDT",
        }, ensure_ascii=False)

    except PositionError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[AgentTools] close_position failed: {e}")
        return json.dumps({"success": False, "error": f"平仓失败: {str(e)}"}, ensure_ascii=False)


@register_tool
async def cancel_order(
    db: AsyncSession,
    user_id: int,
    order_id: int = 0,
) -> str:
    """取消订单"""
    from app.services.trading import OrderExecutor, OrderError

    try:
        # OrderExecutor.cancel_order 是 @staticmethod
        # 签名: (db, order_id, user_id)
        order = await OrderExecutor.cancel_order(
            db=db,
            order_id=int(order_id),
            user_id=user_id,
        )

        return json.dumps({
            "success": True,
            "order_id": order.id,
            "symbol": order.symbol,
            "message": f"订单 #{order.id} 已取消",
        }, ensure_ascii=False)

    except OrderError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[AgentTools] cancel_order failed: {e}")
        return json.dumps({"success": False, "error": f"取消失败: {str(e)}"}, ensure_ascii=False)


# ==================== 分析工具 ====================

@register_tool
async def get_indicators(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
) -> str:
    """获取技术指标"""
    try:
        from app.services.indicator_service import indicator_service
        indicators = await indicator_service.get_or_calculate(symbol.upper(), interval)

        if indicators:
            # 只返回关键指标，避免 token 过多
            summary = {}
            for key in ["rsi", "macd", "macd_signal", "macd_histogram",
                         "ema_20", "ema_50", "sma_20",
                         "bollinger_upper", "bollinger_middle", "bollinger_lower",
                         "atr", "volume_ratio", "close"]:
                if key in indicators and indicators[key] is not None:
                    val = indicators[key]
                    summary[key] = round(float(val), 4) if isinstance(val, (int, float)) else val

            return json.dumps({
                "symbol": symbol.upper(),
                "interval": interval,
                "indicators": summary,
            }, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[AgentTools] get_indicators failed: {e}")

    return json.dumps({"error": f"无法获取 {symbol} {interval} 指标"}, ensure_ascii=False)


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
        }, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[AgentTools] analyze_market failed: {e}")
        return json.dumps({"error": f"市场分析失败: {str(e)}"}, ensure_ascii=False)


@register_tool
async def query_memories(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """查询交易记忆"""
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
        }, ensure_ascii=False)

    data = [
        {
            "symbol": m.symbol,
            "strategy_name": m.strategy_name,
            "trade_result": m.trade_result,
            "pnl_pct": m.pnl_pct,
            "lesson": m.lesson,
            "situation": m.situation,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in memories
    ]
    return json.dumps({"memories": data}, ensure_ascii=False)
