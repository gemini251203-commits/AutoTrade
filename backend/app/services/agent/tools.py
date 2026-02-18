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
import contextvars
from typing import Optional, Dict, Any
from decimal import Decimal

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.order import Order, OrderSide, OrderType, OrderStatus
from app.models.position import Position, PositionSide, PositionStatus, MarginMode
from app.models.wallet import Wallet
from app.models.market import Kline
from app.models.strategy import TradeMemory, Strategy

# ==================== 来源上下文 ====================
# Autopilot 调用前设置此变量，tools 自动使用正确的 note 前缀
agent_source_var = contextvars.ContextVar('agent_source', default='agent')

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

    # 获取实时价格计算未实现盈亏
    from app.services.exchange import BinanceClient
    client = BinanceClient()

    data = []
    for p in positions:
        unrealized_pnl = 0.0
        try:
            ticker = await client.get_ticker(p.symbol)
            mark_price = float(ticker.get("lastPrice", 0)) if ticker else 0
            if mark_price > 0:
                unrealized_pnl = float(p.calculate_unrealized_pnl(Decimal(str(mark_price))))
        except Exception:
            pass

        data.append({
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side.value,
            "size": float(p.size),
            "entry_price": float(p.entry_price),
            "leverage": p.leverage,
            "margin": float(p.margin),
            "unrealized_pnl": unrealized_pnl,
            "stop_loss": float(p.stop_loss) if p.stop_loss else None,
            "take_profit": float(p.take_profit) if p.take_profit else None,
        })
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

        # 根据来源上下文设置 note 前缀
        source_label = agent_source_var.get('agent')
        if source_label == 'autopilot':
            note_prefix = '[Autopilot]'
            note_text = 'Autopilot 自动下单'
        else:
            note_prefix = '[Agent]'
            note_text = 'AI Agent 下单'

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
            note=f"{note_prefix} {note_text}",
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
                        "support_resistance": {
                            "nearest_support": indicators.get("support_resistance", {}).get("nearest_support"),
                            "nearest_resistance": indicators.get("support_resistance", {}).get("nearest_resistance"),
                        },
                        "ema": indicators.get("ema"),
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

                    return json.dumps(result, ensure_ascii=False)
            else:
                logger.warning(f"[AgentTools] Binance klines HTTP {resp.status_code}: {resp.text[:200]}")
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


# ==================== 策略管理工具 ====================


@register_tool
async def list_strategies(
    db: AsyncSession,
    user_id: int,
) -> str:
    """列出所有可用策略 (用户创建的 + 预设模板)"""
    from app.services.quant.strategy import list_templates

    # 1. 用户自己的策略
    result = await db.execute(
        select(Strategy)
        .where(Strategy.user_id == user_id)
        .order_by(desc(Strategy.updated_at))
    )
    user_strategies = result.scalars().all()

    strategies = []
    for s in user_strategies:
        strategies.append({
            "id": s.id,
            "name": s.name,
            "symbol": s.symbol,
            "interval": s.interval,
            "is_active": s.is_active,
            "total_trades": s.total_trades,
            "win_trades": s.win_trades,
            "total_pnl": s.total_pnl,
            "last_signal": s.last_signal,
            "type": "user",
        })

    # 2. 预设模板
    templates = list_templates()
    for t in templates:
        strategies.append({
            "id": t["id"],
            "name": t["name"],
            "symbol": t["symbol"],
            "interval": t["interval"],
            "type": "template",
        })

    return json.dumps({
        "strategies": strategies,
        "user_count": len(user_strategies),
        "template_count": len(templates),
    }, ensure_ascii=False)


@register_tool
async def get_strategy_detail(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
) -> str:
    """查看策略详细配置 (支持用户策略 ID 或模板 ID)"""
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES

    engine = StrategyEngine()

    # 尝试作为数据库 ID 查询
    if strategy_id.isdigit():
        result = await db.execute(
            select(Strategy).where(
                Strategy.id == int(strategy_id),
                Strategy.user_id == user_id,
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy:
            try:
                config = engine.parse_yaml(strategy.config_yaml)
            except Exception:
                config = {}
            return json.dumps({
                "id": strategy.id,
                "name": strategy.name,
                "symbol": strategy.symbol,
                "interval": strategy.interval,
                "config_yaml": strategy.config_yaml,
                "config_parsed": config,
                "is_active": strategy.is_active,
                "total_trades": strategy.total_trades,
                "win_trades": strategy.win_trades,
                "total_pnl": strategy.total_pnl,
                "type": "user",
            }, ensure_ascii=False, default=str)

    # 尝试作为模板 ID 查询
    if strategy_id in STRATEGY_TEMPLATES:
        yaml_content = STRATEGY_TEMPLATES[strategy_id].strip()
        config = engine.parse_yaml(yaml_content)
        return json.dumps({
            "id": strategy_id,
            "name": config.get("name", strategy_id),
            "symbol": config.get("symbol", ""),
            "interval": config.get("interval", "1h"),
            "config_yaml": yaml_content,
            "config_parsed": config,
            "type": "template",
        }, ensure_ascii=False, default=str)

    return json.dumps({"error": f"找不到策略: {strategy_id}"}, ensure_ascii=False)


async def _fetch_klines_map(symbol: str, timeframes: list) -> dict:
    """
    获取多时间框架 K 线数据
    
    Returns:
        {"1h": [klines...], "4h": [klines...], ...}
    """
    from app.core.network import net_manager

    klines_map = {}
    async with net_manager.get_client(timeout=15.0) as client:
        for tf in timeframes:
            try:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={
                        "symbol": symbol,
                        "interval": tf,
                        "limit": 200,
                    },
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    if raw and len(raw) >= 20:
                        klines_map[tf] = [{
                            "open_time": k[0],
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": k[6],
                            "quote_volume": float(k[7]),
                        } for k in raw]
            except Exception as e:
                logger.warning(f"[Tools] 获取 {tf} K线失败: {e}")
    return klines_map


@register_tool
async def evaluate_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
    symbol: str = "",
) -> str:
    """
    评估策略在当前行情下的信号 (不会下单)

    参数:
        strategy_id: 用户策略 ID (数字) 或模板 ID (字符串)
        symbol: 可选, 覆盖策略默认的交易对
    """
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES

    engine = StrategyEngine()

    # 获取策略配置
    config = None
    strategy_name = strategy_id

    if strategy_id.isdigit():
        result = await db.execute(
            select(Strategy).where(
                Strategy.id == int(strategy_id),
                Strategy.user_id == user_id,
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy:
            config = engine.parse_yaml(strategy.config_yaml)
            strategy_name = strategy.name
    elif strategy_id in STRATEGY_TEMPLATES:
        config = engine.parse_yaml(STRATEGY_TEMPLATES[strategy_id].strip())
        strategy_name = config.get("name", strategy_id)

    if not config:
        return json.dumps({"error": f"找不到策略: {strategy_id}"}, ensure_ascii=False)

    # 如果指定了 symbol，覆盖策略默认的
    target_symbol = (symbol or config.get("symbol", "BTCUSDT")).upper()
    config["symbol"] = target_symbol

    # 获取多时间框架 K 线数据
    required_tfs = config.get("_required_timeframes", [config.get("interval", "1h")])
    
    try:
        klines_map = await _fetch_klines_map(target_symbol, required_tfs)
    except Exception as e:
        return json.dumps({"error": f"获取K线异常: {str(e)}"}, ensure_ascii=False)

    if not klines_map:
        return json.dumps({"error": "无法获取任何时间框架的K线数据"}, ensure_ascii=False)

    # 执行策略评估
    try:
        signal = engine.evaluate(config, klines_map=klines_map)
    except Exception as e:
        return json.dumps({"error": f"策略评估失败: {str(e)}"}, ensure_ascii=False)

    return json.dumps({
        "strategy_name": strategy_name,
        "symbol": target_symbol,
        "timeframes": required_tfs,
        "signal_type": signal.signal_type.value,
        "has_signal": signal.has_signal,
        "side": signal.side.value if signal.side else None,
        "confidence": round(signal.confidence, 2),
        "conditions_met": [str(c) for c in signal.conditions_met],
        "conditions_failed": [str(c) for c in signal.conditions_failed],
        "risk_config": signal.risk_config,
        "summary": signal.summary(),
    }, ensure_ascii=False, default=str)


@register_tool
async def run_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
    symbol: str = "",
) -> str:
    """
    完整执行策略: 评估 → 风控 → 下单

    只有当策略产生入场信号 AND 通过风控时才下单。
    """
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES
    from app.services.quant.risk_guard import RiskGuard
    from app.services.trading.position_manager import PositionManager
    from app.services.quant.indicators import get_indicator

    engine = StrategyEngine()
    risk_guard = RiskGuard()

    # 获取策略配置
    config = None
    strategy_name = strategy_id

    if strategy_id.isdigit():
        result = await db.execute(
            select(Strategy).where(
                Strategy.id == int(strategy_id),
                Strategy.user_id == user_id,
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy:
            config = engine.parse_yaml(strategy.config_yaml)
            strategy_name = strategy.name
    elif strategy_id in STRATEGY_TEMPLATES:
        config = engine.parse_yaml(STRATEGY_TEMPLATES[strategy_id].strip())
        strategy_name = config.get("name", strategy_id)

    if not config:
        return json.dumps({"error": f"找不到策略: {strategy_id}"}, ensure_ascii=False)

    target_symbol = (symbol or config.get("symbol", "BTCUSDT")).upper()
    config["symbol"] = target_symbol

    # 1. 获取多时间框架 K 线
    required_tfs = config.get("_required_timeframes", [config.get("interval", "1h")])
    try:
        klines_map = await _fetch_klines_map(target_symbol, required_tfs)
    except Exception as e:
        return json.dumps({"error": f"获取K线异常: {str(e)}"}, ensure_ascii=False)

    if not klines_map:
        return json.dumps({"error": "无法获取K线数据"}, ensure_ascii=False)

    # 取主时间框架 K 线 (用于价格和 ATR)
    default_interval = config.get("interval", "1h")
    main_klines = klines_map.get(default_interval, list(klines_map.values())[0])

    # 2. 策略评估
    try:
        signal = engine.evaluate(config, klines_map=klines_map)
    except Exception as e:
        return json.dumps({"error": f"策略评估异常: {str(e)}"}, ensure_ascii=False)

    if not signal.has_signal:
        return json.dumps({
            "action": "no_signal",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": f"策略 '{strategy_name}' 当前无交易信号",
            "conditions_met": [str(c) for c in signal.conditions_met],
            "conditions_failed": [str(c) for c in signal.conditions_failed],
        }, ensure_ascii=False, default=str)

    if signal.signal_type.value == "exit":
        return json.dumps({
            "action": "exit_signal",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": f"策略 '{strategy_name}' 建议平仓",
            "side": signal.side.value if signal.side else None,
            "conditions_met": [str(c) for c in signal.conditions_met],
        }, ensure_ascii=False, default=str)

    # 3. 风控检查
    risk_config = signal.risk_config
    risk_config = risk_guard.clamp_params(risk_config)

    # 获取钱包余额
    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = wallet_result.scalar_one_or_none()
    wallet_balance = float(wallet.balance) if wallet else 0.0

    if wallet_balance <= 0:
        return json.dumps({"error": "钱包余额不足"}, ensure_ascii=False)

    # 获取持仓
    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    open_positions = [
        {"symbol": p.symbol, "side": p.side.value, "margin": float(p.margin)}
        for p in pos_result.scalars().all()
    ]

    # 获取今日统计
    from datetime import datetime, timedelta
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_orders = await db.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.created_at >= today_start,
            Order.status == OrderStatus.FILLED,
        )
    )
    today_trades = len(today_orders.scalars().all())

    risk_passed, risk_results = risk_guard.check_all(
        signal_side=signal.side.value if signal.side else "buy",
        symbol=target_symbol,
        position_pct=risk_config.get("position_pct", 10),
        leverage=risk_config.get("leverage", 1),
        stop_loss_pct=risk_config.get("stop_loss_pct", 3),
        take_profit_pct=risk_config.get("take_profit_pct", 9),
        wallet_balance=wallet_balance,
        open_positions=open_positions,
        today_trades=today_trades,
        today_pnl=0.0,
    )

    if not risk_passed:
        failed_rules = [str(r) for r in risk_results if not r.passed]
        return json.dumps({
            "action": "risk_blocked",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": "信号被风控拦截",
            "risk_failed": failed_rules,
            "signal": signal.summary(),
        }, ensure_ascii=False, default=str)

    # 4. 自动下单
    current_price = Decimal(str(main_klines[-1]["close"]))
    leverage = risk_config.get("leverage", 1)
    position_pct = risk_config.get("position_pct", 10)

    # L4: 波动率自适应仓位
    if risk_config.get("volatility_adjust"):
        try:
            atr_val = get_indicator("atr", main_klines)
            if atr_val and float(current_price) > 0:
                atr_pct = atr_val / float(current_price) * 100
                # ATR% < 1% 正常仓位, ATR% > 3% 缩至 1/3
                vol_factor = max(0.33, min(1.0, 1.0 / atr_pct))
                original_pct = position_pct
                position_pct = round(position_pct * vol_factor, 1)
                logger.info(
                    f"[Strategy] 波动率调整: ATR%={atr_pct:.2f}%, "
                    f"仓位 {original_pct}% → {position_pct}%"
                )
        except Exception as e:
            logger.warning(f"[Strategy] 波动率调整失败: {e}")

    trade_amount = wallet_balance * position_pct / 100
    quantity = Decimal(str(round(trade_amount / float(current_price), 4)))

    side_map = {"buy": PositionSide.LONG, "sell": PositionSide.SHORT}
    position_side = side_map.get(signal.side.value, PositionSide.LONG) if signal.side else PositionSide.LONG

    # 计算止损止盈 (L2: 支持动态止损)
    stop_type = risk_config.get("stop_type", "fixed")
    stop_loss_pct = risk_config.get("stop_loss_pct", 3)
    take_profit_pct = risk_config.get("take_profit_pct", 9)

    if stop_type == "atr":
        # ATR 止损: 止损距离 = ATR * multiplier
        try:
            atr_val = get_indicator("atr", main_klines)
            multiplier = risk_config.get("atr_stop_multiplier", 2)
            if atr_val:
                atr_stop_distance = Decimal(str(atr_val * multiplier))
                if position_side == PositionSide.LONG:
                    stop_loss = current_price - atr_stop_distance
                    take_profit = current_price + atr_stop_distance * Decimal("3") if take_profit_pct else None
                else:
                    stop_loss = current_price + atr_stop_distance
                    take_profit = current_price - atr_stop_distance * Decimal("3") if take_profit_pct else None
            else:
                # ATR 计算失败，回退到固定止损
                stop_loss, take_profit = _calc_fixed_stops(
                    current_price, position_side, stop_loss_pct, take_profit_pct
                )
        except Exception:
            stop_loss, take_profit = _calc_fixed_stops(
                current_price, position_side, stop_loss_pct, take_profit_pct
            )
    elif stop_type == "trailing":
        # 追踪止损: 先用固定止损开仓，追踪逻辑在 position_manager 层处理
        trailing_pct = risk_config.get("trailing_pct", 1.5)
        stop_loss, take_profit = _calc_fixed_stops(
            current_price, position_side, trailing_pct, take_profit_pct
        )
    else:
        # 固定止损（默认）
        stop_loss, take_profit = _calc_fixed_stops(
            current_price, position_side, stop_loss_pct, take_profit_pct
        )

    try:
        source = agent_source_var.get()
        position = await PositionManager.open_position(
            db=db,
            user_id=user_id,
            symbol=target_symbol,
            side=position_side,
            quantity=quantity,
            entry_price=current_price,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=source,
            open_reason=f"策略 '{strategy_name}' 信号: {signal.summary()}",
        )
        await db.commit()

        return json.dumps({
            "action": "executed",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "side": position_side.value,
            "quantity": str(quantity),
            "entry_price": str(current_price),
            "leverage": leverage,
            "stop_loss": str(stop_loss) if stop_loss else None,
            "stop_type": stop_type,
            "take_profit": str(take_profit) if take_profit else None,
            "position_pct_actual": position_pct,
            "position_id": position.id,
            "message": f"策略 '{strategy_name}' 已执行交易",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"下单失败: {str(e)}"}, ensure_ascii=False)


def _calc_fixed_stops(
    current_price: Decimal,
    position_side,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple:
    """计算固定百分比止损止盈"""
    if position_side.value == "long":
        stop_loss = current_price * (1 - Decimal(str(stop_loss_pct)) / 100) if stop_loss_pct else None
        take_profit = current_price * (1 + Decimal(str(take_profit_pct)) / 100) if take_profit_pct else None
    else:
        stop_loss = current_price * (1 + Decimal(str(stop_loss_pct)) / 100) if stop_loss_pct else None
        take_profit = current_price * (1 - Decimal(str(take_profit_pct)) / 100) if take_profit_pct else None
    return stop_loss, take_profit


def _build_validation_report(config: dict) -> dict:
    """生成策略验证报告 — 让 AI 和用户确认策略实际包含什么"""
    entry = config.get("entry", {})
    exit_block = config.get("exit", {})
    risk = config.get("risk", {})

    entry_conds = entry.get("conditions", [])
    exit_conds = exit_block.get("conditions", [])

    # 收集使用的指标
    indicators_used = set()
    for cond in entry_conds + exit_conds:
        if "indicator" in cond:
            indicators_used.add(cond["indicator"])
        if "reference" in cond:
            indicators_used.add(cond["reference"])

    # 收集使用的功能
    features = []
    for cond in entry_conds + exit_conds:
        if "timeframe" in cond:
            features.append("多时间框架")
        if "cross" in cond:
            features.append("时序穿越")
        if "expression" in cond:
            features.append("自定义表达式")
        if "weight" in cond:
            features.append("权重评分")
    if config.get("scoring"):
        features.append(f"评分阈值={config['scoring'].get('min_score', '?')}")
    if config.get("stages"):
        features.append(f"分批建仓({len(config['stages'])}阶段)")
    if config.get("time_filter"):
        features.append("时间过滤")
    if risk.get("stop_type") and risk["stop_type"] != "fixed":
        features.append(f"动态止损({risk['stop_type']})")
    if risk.get("volatility_adjust"):
        features.append("波动率自适应")

    report = {
        "entry_conditions": len(entry_conds),
        "exit_conditions": len(exit_conds),
        "entry_operator": entry.get("operator", "AND"),
        "exit_operator": exit_block.get("operator", "OR"),
        "indicators_used": sorted(indicators_used),
        "risk_summary": {
            "side": risk.get("side", "未设置"),
            "leverage": risk.get("leverage", "未设置"),
            "position_pct": risk.get("position_pct", "未设置"),
            "stop_loss_pct": risk.get("stop_loss_pct", "未设置"),
            "take_profit_pct": risk.get("take_profit_pct", "未设置"),
            "stop_type": risk.get("stop_type", "fixed"),
        },
        "required_timeframes": config.get("_required_timeframes", []),
        "features": sorted(set(features)) if features else ["基础策略"],
    }

    # 警告
    warnings = []
    if len(entry_conds) == 0:
        warnings.append("⚠️ 没有入场条件")
    if len(exit_conds) == 0:
        warnings.append("⚠️ 没有出场条件")
    if not risk.get("side"):
        warnings.append("⚠️ 未设置 risk.side (buy/sell)")
    if warnings:
        report["warnings"] = warnings

    return report


@register_tool
async def create_strategy(
    db: AsyncSession,
    user_id: int,
    name: str = "",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    config_yaml: str = "",
) -> str:
    """
    创建新策略并保存到数据库

    参数:
        name: 策略名称
        symbol: 交易对
        interval: K 线周期
        config_yaml: YAML 格式的策略配置
    """
    from app.services.quant.strategy import StrategyEngine

    if not name or not config_yaml:
        return json.dumps({"error": "缺少必要参数: name 和 config_yaml"}, ensure_ascii=False)

    engine = StrategyEngine()
    try:
        config = engine.parse_yaml(config_yaml)
    except ValueError as e:
        return json.dumps({"error": f"YAML 配置验证失败: {str(e)}"}, ensure_ascii=False)

    strategy = Strategy(
        user_id=user_id,
        name=name,
        symbol=symbol.upper(),
        interval=interval,
        config_yaml=config_yaml,
        is_active=False,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)

    # 生成验证报告
    report = _build_validation_report(config)

    return json.dumps({
        "action": "created",
        "id": strategy.id,
        "name": strategy.name,
        "symbol": strategy.symbol,
        "interval": strategy.interval,
        "message": f"策略 '{name}' 已创建 (ID: {strategy.id})，默认未启用",
        "validation_report": report,
    }, ensure_ascii=False)


@register_tool
async def update_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
    name: str = "",
    symbol: str = "",
    interval: str = "",
    config_yaml: str = "",
) -> str:
    """
    修改已有策略配置

    参数:
        strategy_id: 策略 ID (数字)
        name/symbol/interval/config_yaml: 要更新的字段 (空字符串表示不修改)
    """
    from app.services.quant.strategy import StrategyEngine

    if not strategy_id.isdigit():
        return json.dumps({"error": f"无效的策略 ID: {strategy_id}"}, ensure_ascii=False)

    result = await db.execute(
        select(Strategy).where(
            Strategy.id == int(strategy_id),
            Strategy.user_id == user_id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return json.dumps({"error": f"找不到策略 ID: {strategy_id}"}, ensure_ascii=False)

    # 验证新的 YAML (如果提供了)
    if config_yaml:
        engine = StrategyEngine()
        try:
            engine.parse_yaml(config_yaml)
        except ValueError as e:
            return json.dumps({"error": f"YAML 配置验证失败: {str(e)}"}, ensure_ascii=False)
        strategy.config_yaml = config_yaml

    if name:
        strategy.name = name
    if symbol:
        strategy.symbol = symbol.upper()
    if interval:
        strategy.interval = interval

    await db.commit()

    # 生成验证报告 (用最新 YAML)
    report = {}
    try:
        final_config = engine.parse_yaml(strategy.config_yaml) if config_yaml else None
        if final_config:
            report = _build_validation_report(final_config)
    except Exception:
        pass

    result = {
        "action": "updated",
        "id": strategy.id,
        "name": strategy.name,
        "symbol": strategy.symbol,
        "interval": strategy.interval,
        "message": f"策略 '{strategy.name}' (ID: {strategy.id}) 已更新",
    }
    if report:
        result["validation_report"] = report
    return json.dumps(result, ensure_ascii=False)


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
