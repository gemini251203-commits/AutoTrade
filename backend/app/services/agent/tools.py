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

# 完整交易规则从 exchange_rules 模块导入 (580 个交易对)
from app.services.exchange_rules import (
    get_min_notional,
    get_qty_precision,
    round_quantity_up,
    validate_order as validate_exchange_rules,
)


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
    stop_loss: float = 0,
    take_profit: float = 0,
) -> str:
    """下单 (含 Binance 规则预检验)"""
    from app.services.trading import OrderExecutor, OrderError

    try:
        symbol = symbol.upper()

        # ==================== 预检验: Binance 交易规则 ====================
        from app.services.exchange import BinanceClient
        client = BinanceClient()
        try:
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker.get("lastPrice", 0)) if ticker else 0
        except Exception:
            current_price = 0

        if current_price > 0:
            # 使用完整交易规则模块验证
            validation = validate_exchange_rules(symbol, quantity, current_price, leverage)
            if not validation["valid"]:
                return json.dumps({
                    "success": False,
                    "error": validation["error"],
                    "suggestion": validation["suggestion"],
                }, ensure_ascii=False)

            # 检查保证金是否够
            notional = quantity * current_price
            margin = notional / leverage if leverage > 0 else notional
            wallet_result = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallet = wallet_result.scalar_one_or_none()
            if wallet and margin > float(wallet.balance):
                available = float(wallet.balance)
                # 计算建议的修正参数
                safe_margin = available * 0.3  # 使用30%可用余额
                safe_notional = safe_margin * leverage
                safe_qty = safe_notional / current_price
                # 按步长取整
                safe_qty = round_quantity_up(symbol, safe_qty)
                return json.dumps({
                    "success": False, 
                    "error": (
                        f"保证金不足: 需要 ${margin:,.2f} (名义${notional:,.2f} / {leverage}x), "
                        f"但可用余额仅 ${available:,.2f}。"
                    ),
                    "suggested_fix": {
                        "quantity": safe_qty,
                        "leverage": leverage,
                        "margin": round(safe_margin, 2),
                        "notional": round(safe_notional, 2),
                    },
                    "hint": f"建议使用 quantity={safe_qty}, leverage={leverage} 重试下单。",
                }, ensure_ascii=False)

        # ==================== 通过预检验, 执行下单 ====================
        order_side = OrderSide(side.lower())
        otype = OrderType(order_type.lower())
        order_price = Decimal(str(price)) if price and float(price) > 0 else None

        # 止损止盈参数
        sl = Decimal(str(stop_loss)) if stop_loss and float(stop_loss) > 0 else None
        tp = Decimal(str(take_profit)) if take_profit and float(take_profit) > 0 else None

        order = await OrderExecutor.create_order(
            db=db,
            user_id=user_id,
            symbol=symbol,
            side=order_side,
            order_type=otype,
            quantity=Decimal(str(quantity)),
            price=order_price,
            leverage=int(leverage),
            stop_loss=sl,
            take_profit=tp,
            note=f"[Agent] AI Agent 下单",
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
            "stop_loss": float(order.stop_loss) if order.stop_loss else None,
            "take_profit": float(order.take_profit) if order.take_profit else None,
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
        # 直接从 Binance API 获取 K 线，绕过 indicator_service
        from app.services.exchange import BinanceClient
        client = BinanceClient()
        raw_klines = await client.get_klines(symbol.upper(), interval, limit=100)

        if raw_klines and len(raw_klines) >= 15:
            closes = [float(k["close"]) for k in raw_klines]
            volumes = [float(k["volume"]) for k in raw_klines]

            # RSI(14) 计算
            rsi = None
            if len(closes) >= 15:
                changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
                gains = [c if c > 0 else 0 for c in changes[-14:]]
                losses = [-c if c < 0 else 0 for c in changes[-14:]]
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi = round(100 - (100 / (1 + rs)), 2)
                else:
                    rsi = 100.0

            # MA 均线
            ma7 = round(sum(closes[-7:]) / 7, 2) if len(closes) >= 7 else None
            ma25 = round(sum(closes[-25:]) / 25, 2) if len(closes) >= 25 else None

            # 当前价格
            current_price = closes[-1]

            # 趋势判断
            trend = "neutral"
            if rsi and ma7 and ma25:
                if rsi > 50 and current_price > ma7 > ma25:
                    trend = "bullish"
                elif rsi < 50 and current_price < ma7 < ma25:
                    trend = "bearish"

            return json.dumps({
                "symbol": symbol.upper(),
                "interval": interval,
                "current_price": round(current_price, 2),
                "trend": trend,
                "indicators": {
                    "rsi": rsi,
                    "ma7": ma7,
                    "ma25": ma25,
                },
            }, ensure_ascii=False)

        logger.warning(f"[AgentTools] get_indicators: no klines from Binance for {symbol}/{interval}")
    except Exception as e:
        logger.warning(f"[AgentTools] get_indicators Binance direct failed: {e}")

    # Fallback: 尝试 indicator_service
    try:
        from app.services.indicator_service import indicator_service
        result = await indicator_service.get_or_calculate(symbol.upper(), interval)
        if result and result.get("indicators"):
            return json.dumps({
                "symbol": symbol.upper(),
                "interval": interval,
                "current_price": result.get("current_price"),
                "trend": result.get("trend"),
                "indicators": result["indicators"],
            }, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[AgentTools] get_indicators fallback also failed: {e}")

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
        }, ensure_ascii=False)

    source_labels = {
        "manual": "手动", "agent": "AI Agent",
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
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in memories
    ]
    return json.dumps({"memories": data, "total": len(data)}, ensure_ascii=False)

