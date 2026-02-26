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
from app.core.time_utils import utc_now

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
        return json.dumps(info, ensure_ascii=False)

    return json.dumps({"error": f"无法获取 {symbol} 资金费率"}, ensure_ascii=False)

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

# 统一品种管理器 (替代散落的 exchange_rules 字典)
from app.models.security import security_manager


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
            # 使用统一品种管理器验证
            validation = security_manager.validate_order(symbol, quantity, current_price, leverage)
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
                safe_qty = float(security_manager.round_quantity_up(symbol, safe_qty))
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

        # 根据来源上下文确定 source
        source_label = agent_source_var.get('agent')

        # ==================== 通过 Pipeline 统一下单 ====================
        from app.core.pipeline import get_pipeline
        
        pipeline = get_pipeline(user_id)
        
        # 获取余额和持仓信息用于风控
        wallet_result2 = await db.execute(
            select(Wallet).where(Wallet.user_id == user_id)
        )
        wallet2 = wallet_result2.scalar_one_or_none()
        available_balance = Decimal(str(wallet2.balance)) if wallet2 else Decimal("0")
        total_equity = Decimal(str(wallet2.total_equity)) if wallet2 else Decimal("0")
        
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.status == PositionStatus.OPEN,
            )
        )
        positions = pos_result.scalars().all()
        open_positions = [
            {"symbol": p.symbol, "side": p.side.value, "size": float(p.size)}
            for p in positions
        ]
        
        result = await pipeline.submit_order(
            db=db,
            symbol=symbol,
            side=side.lower(),
            quantity=Decimal(str(quantity)),
            leverage=int(leverage),
            price=Decimal(str(current_price)) if current_price else None,
            stop_loss=sl,
            take_profit=tp,
            source=source_label,
            note=f"[{source_label.title()}] 下单",
            available_balance=available_balance,
            total_equity=total_equity,
            open_positions=open_positions,
        )
        
        if result.get("success"):
            result["message"] = "订单已通过 Pipeline 执行"
        
        return json.dumps(result, ensure_ascii=False, default=str)

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
            "created_at": m.created_at.isoformat() + "Z" if m.created_at else "",
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
    if str(strategy_id).isdigit():
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

    if str(strategy_id).isdigit():
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
    from app.services.risk.risk_model import RiskModel
    from app.services.trading.position_manager import PositionManager
    from app.services.quant.indicators import get_indicator

    engine = StrategyEngine()
    risk_guard = RiskModel()

    # 获取策略配置
    config = None
    strategy_name = strategy_id

    if str(strategy_id).isdigit():
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

    # 3. 获取钱包余额和持仓 (供 Pipeline 风控使用)
    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = wallet_result.scalar_one_or_none()
    wallet_balance = float(wallet.balance) if wallet else 0.0

    if wallet_balance <= 0:
        return json.dumps({"error": "钱包余额不足"}, ensure_ascii=False)

    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    open_positions = [
        {"symbol": p.symbol, "side": p.side.value, "size": float(p.size), "margin": float(p.margin)}
        for p in pos_result.scalars().all()
    ]

    # 4. 计算下单参数
    risk_config = signal.risk_config
    current_price = Decimal(str(main_klines[-1]["close"]))
    leverage = risk_config.get("leverage", 1)
    position_pct = risk_config.get("position_pct", 10)

    # L4: 波动率自适应仓位
    if risk_config.get("volatility_adjust"):
        try:
            atr_val = get_indicator("atr", main_klines)
            if atr_val and float(current_price) > 0:
                atr_pct = atr_val / float(current_price) * 100
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
                stop_loss, take_profit = _calc_fixed_stops(
                    current_price, position_side, stop_loss_pct, take_profit_pct
                )
        except Exception:
            stop_loss, take_profit = _calc_fixed_stops(
                current_price, position_side, stop_loss_pct, take_profit_pct
            )
    elif stop_type == "trailing":
        trailing_pct = risk_config.get("trailing_pct", 1.5)
        stop_loss, take_profit = _calc_fixed_stops(
            current_price, position_side, trailing_pct, take_profit_pct
        )
    else:
        stop_loss, take_profit = _calc_fixed_stops(
            current_price, position_side, stop_loss_pct, take_profit_pct
        )

    # 5. 通过 Pipeline 统一下单 (Risk → Execution)
    try:
        from app.core.pipeline import get_pipeline
        
        source = agent_source_var.get()
        pipeline = get_pipeline(user_id)
        
        order_side = "buy" if position_side == PositionSide.LONG else "sell"
        
        result = await pipeline.submit_from_signal(
            db=db,
            symbol=target_symbol,
            side=order_side,
            quantity=quantity,
            leverage=leverage,
            price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=source,
            strategy_name=strategy_name,
            available_balance=Decimal(str(wallet_balance)),
            total_equity=Decimal(str(wallet.total_equity)) if wallet else Decimal("0"),
            open_positions=open_positions,
        )
        
        if result.get("success"):
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
                "order_id": result.get("order_id"),
                "message": f"策略 '{strategy_name}' 已通过 Pipeline 执行",
            }, ensure_ascii=False, default=str)
        else:
            return json.dumps({
                "action": "risk_blocked",
                "strategy_name": strategy_name,
                "symbol": target_symbol,
                "message": result.get("error", "Pipeline 执行失败"),
                "signal": signal.summary(),
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
    is_pipeline = any(k in config for k in ("alphas", "portfolio", "execution"))
    
    if is_pipeline:
        alphas = config.get("alphas", [])
        return {
            "is_pipeline": True,
            "alphas": len(alphas),
            "portfolio": config.get("portfolio", {}).get("type", "unknown"),
            "risk": config.get("risk", {}).get("type", "unknown"),
            "execution": config.get("execution", {}).get("type", "unknown"),
            "features": ["Pipeline架构"]
        }

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
        "is_pipeline": False,
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

    # 强校验：是否存在不支持的指标
    report = _build_validation_report(config)
    if not report.get("is_valid", False):
        error_msgs = []
        if report.get("unknown_indicators"):
            error_msgs.append(f"使用了系统不支持的指标: {', '.join(report['unknown_indicators'])}")
        if report.get("syntax_errors"):
            error_msgs.extend(report["syntax_errors"])
        if error_msgs:
            return json.dumps({"error": f"策略配置无效: {'; '.join(error_msgs)}"}, ensure_ascii=False)

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
    strategy_id: int = 0,
    config_yaml: str = "",
    name: str = "",
    interval: str = "",
) -> str:
    """
    安全更新策略 (带 YAML 验证 + 干跑评估)

    在保存前验证:
    1. YAML 语法和结构是否正确
    2. 使用的指标是否全部受支持
    3. 干跑评估是否能正常执行 (不下单)

    参数:
        strategy_id: 策略 ID
        config_yaml: 新的 YAML 配置 (可选, 不传则不修改配置)
        name: 新的策略名称 (可选)
        interval: 新的 K 线周期 (可选)
    """
    from app.services.quant.strategy import StrategyEngine

    if not strategy_id:
        return json.dumps({"error": "缺少 strategy_id"}, ensure_ascii=False)

    result = await db.execute(
        select(Strategy).where(
            Strategy.id == int(strategy_id),
            Strategy.user_id == user_id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return json.dumps({"error": f"找不到策略 ID={strategy_id}"}, ensure_ascii=False)

    # 保存旧配置用于回滚
    old_yaml = strategy.config_yaml
    old_name = strategy.name
    old_interval = strategy.interval

    engine = StrategyEngine()

    # 如果提供了新 YAML, 验证它
    if config_yaml:
        # Step 1: 解析 YAML
        try:
            config = engine.parse_yaml(config_yaml)
        except ValueError as e:
            return json.dumps({
                "error": f"YAML 解析失败: {str(e)}",
                "hint": "请检查 YAML 语法是否正确",
            }, ensure_ascii=False)

        # Step 2: 验证指标和结构
        report = _build_validation_report(config)
        if not report.get("is_valid", False):
            error_msgs = []
            if report.get("unknown_indicators"):
                error_msgs.append(f"不支持的指标: {', '.join(report['unknown_indicators'])}")
            if report.get("syntax_errors"):
                error_msgs.extend(report["syntax_errors"])
            return json.dumps({
                "error": f"策略配置无效: {'; '.join(error_msgs)}",
                "old_config_preserved": True,
            }, ensure_ascii=False)

        # Step 3: 干跑评估 — 确保策略能正常运行
        try:
            target_symbol = config.get("symbol", strategy.symbol)
            required_tfs = config.get("_required_timeframes", [config.get("interval", strategy.interval)])
            klines_map = await _fetch_klines_map(target_symbol, required_tfs)
            if klines_map:
                engine.evaluate(config, klines_map=klines_map)
        except Exception as e:
            return json.dumps({
                "error": f"干跑评估失败 (策略无法运行): {str(e)}",
                "old_config_preserved": True,
                "hint": "请检查 entry/exit 条件中的指标名称和参数是否正确",
            }, ensure_ascii=False)

        # 所有验证通过, 更新配置
        strategy.config_yaml = config_yaml

    # 更新其他字段
    if name:
        strategy.name = name
    if interval:
        strategy.interval = interval

    await db.commit()
    await db.refresh(strategy)

    changes = []
    if config_yaml:
        changes.append("配置已更新")
    if name:
        changes.append(f"名称→{name}")
    if interval:
        changes.append(f"周期→{interval}")

    return json.dumps({
        "action": "updated",
        "id": strategy.id,
        "name": strategy.name,
        "changes": changes,
        "message": f"策略 '{strategy.name}' (ID:{strategy.id}) 更新成功: {', '.join(changes)}",
    }, ensure_ascii=False)


@register_tool
async def list_modules(
    db: AsyncSession,
    user_id: int,
    layer: str = "",
) -> str:
    """
    查询可用的策略模块目录

    参数:
        layer: 指定层 (alpha/portfolio/risk/execution)，空=显示全部

    返回:
        各层可用模块清单，含参数说明
    """
    from app.services.quant.module_registry import list_modules as _list, get_registry_summary

    if layer and layer not in ("alpha", "portfolio", "risk", "execution"):
        return json.dumps({"error": f"未知层: {layer}。可选: alpha/portfolio/risk/execution"}, ensure_ascii=False)

    modules = _list(layer or None)

    if not modules:
        return json.dumps({"error": f"层 '{layer}' 没有可用模块"}, ensure_ascii=False)

    result = []
    for m in modules:
        result.append(m.to_dict())

    summary = get_registry_summary()

    return json.dumps({
        "modules": result,
        "summary": summary,
        "hint": "使用 create_pipeline_strategy 时，从每层选择一个模块并配置参数",
    }, ensure_ascii=False, indent=2)


@register_tool
async def create_pipeline_strategy(
    db: AsyncSession,
    user_id: int,
    name: str = "",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    config_yaml: str = "",
) -> str:
    """
    创建多模块流水线策略并保存到数据库

    参数:
        name: 策略名称
        symbol: 交易对
        interval: K 线周期
        config_yaml: YAML 格式的 pipeline 策略配置
    """
    from app.services.quant.strategy import StrategyEngine

    if not name or not config_yaml:
        return json.dumps({"error": "缺少必要参数: name 和 config_yaml"}, ensure_ascii=False)

    engine = StrategyEngine()
    try:
        config = engine.parse_yaml(config_yaml)
    except ValueError as e:
        return json.dumps({"error": f"YAML 配置验证失败: {str(e)}"}, ensure_ascii=False)

    report = _build_validation_report(config)

    strategy = Strategy(
        user_id=user_id,
        name=name,
        symbol=symbol.upper(),
        interval=interval,
        config_yaml=config_yaml,
        strategy_type="pipeline",
        is_active=False,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)

    return json.dumps({
        "action": "created",
        "id": strategy.id,
        "name": strategy.name,
        "symbol": strategy.symbol,
        "interval": strategy.interval,
        "message": f"流水线策略 '{name}' 已创建 (ID: {strategy.id})，默认未启用",
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

    if not str(strategy_id).isdigit():
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
    report = {}
    if config_yaml:
        engine = StrategyEngine()
        try:
            config = engine.parse_yaml(config_yaml)
        except ValueError as e:
            return json.dumps({"error": f"YAML 配置解析失败: {str(e)}"}, ensure_ascii=False)
        
        # 强校验新的 YAML
        report = _build_validation_report(config)
        if not report.get("is_valid", False):
            error_msgs = []
            if report.get("unknown_indicators"):
                error_msgs.append(f"使用了系统不支持的指标: {', '.join(report['unknown_indicators'])}")
            if report.get("syntax_errors"):
                error_msgs.extend(report["syntax_errors"])
            if error_msgs:
                return json.dumps({"error": f"策略配置无效无法更新: {'; '.join(error_msgs)}"}, ensure_ascii=False)
                
        strategy.config_yaml = config_yaml

    if name:
        strategy.name = name
    if symbol:
        strategy.symbol = symbol.upper()
    if interval:
        strategy.interval = interval

    await db.commit()

    await db.commit()

    # 如果没提供新的 YAML，生成旧 YAML 的验证报告
    if not config_yaml:
        try:
            engine = StrategyEngine()
            final_config = engine.parse_yaml(strategy.config_yaml)
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


# ==================== 交管中心工具 ====================

@register_tool
async def manage_autopilot(
    db: AsyncSession,
    user_id: int,
    action: str = "status",
    symbols: str = "BTCUSDT",
    interval: str = "15m",
) -> str:
    """
    管理自动交易 (AutoPilot)
    
    action 可选:
    - status: 查询当前状态
    - start: 启动自动交易
    - stop: 停止自动交易
    - run_once: 手动触发一次决策
    - logs: 查看最近日志
    """
    from app.services.agent.autopilot import autopilot
    
    try:
        action = action.lower().strip()
        
        if action == "status":
            status = autopilot.get_status(user_id)
            return json.dumps({
                "action": "status",
                **status,
            }, ensure_ascii=False, default=str)
        
        elif action == "start":
            symbol_list = [s.strip().upper() for s in symbols.split(",")]
            await autopilot.start(
                user_id=user_id,
                config={
                    "symbols": symbol_list,
                    "interval": interval,
                    "intervals": [interval],
                },
            )
            return json.dumps({
                "action": "started",
                "symbols": symbol_list,
                "interval": interval,
                **autopilot.get_status(user_id),
            }, ensure_ascii=False, default=str)
        
        elif action == "stop":
            await autopilot.stop(user_id)
            return json.dumps({
                "action": "stopped",
                "message": "AutoPilot 已停止",
            }, ensure_ascii=False)
        
        elif action == "run_once":
            symbol = symbols.split(",")[0].strip().upper()
            reply = await autopilot.run_once(user_id, symbol)
            return json.dumps({
                "action": "run_once",
                "symbol": symbol,
                "reply": reply,
            }, ensure_ascii=False, default=str)
        
        elif action == "logs":
            logs = await autopilot.get_logs(user_id=user_id, limit=10)
            return json.dumps({
                "action": "logs",
                "count": len(logs),
                "logs": logs,
            }, ensure_ascii=False, default=str)
        
        else:
            return json.dumps({
                "error": f"未知操作: {action}",
                "valid_actions": ["status", "start", "stop", "run_once", "logs"],
            }, ensure_ascii=False)
    
    except Exception as e:
        logger.error(f"[AgentTools] manage_autopilot failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def manage_grid(
    db: AsyncSession,
    user_id: int,
    action: str = "list",
    symbol: str = "BTCUSDT",
    upper_price: float = 0,
    lower_price: float = 0,
    grid_count: int = 10,
    investment: float = 100,
    leverage: int = 1,
    grid_id: int = 0,
) -> str:
    """
    管理网格交易
    
    action 可选:
    - list: 查看所有网格机器人
    - start: 创建并启动网格 (需要 symbol/upper_price/lower_price/grid_count/investment)
    - stop: 停止网格 (需要 grid_id)
    - delete: 删除网格 (需要 grid_id)
    """
    from app.services.grid import GridStrategy
    
    try:
        action = action.lower().strip()
        
        if action == "list":
            bots = await GridStrategy.get_user_grid_bots(db, user_id)
            bot_list = []
            for b in bots:
                bot_list.append({
                    "id": b.id,
                    "name": b.name,
                    "symbol": b.symbol,
                    "status": b.status.value if hasattr(b.status, 'value') else str(b.status),
                    "upper_price": str(b.upper_price),
                    "lower_price": str(b.lower_price),
                    "grid_count": b.grid_count,
                    "investment": str(b.investment),
                    "total_profit": str(b.total_profit),
                    "filled_buy_count": b.filled_buy_count,
                    "filled_sell_count": b.filled_sell_count,
                })
            return json.dumps({
                "action": "list",
                "count": len(bot_list),
                "bots": bot_list,
            }, ensure_ascii=False, default=str)
        
        elif action == "start":
            if upper_price <= 0 or lower_price <= 0:
                return json.dumps({"error": "必须提供 upper_price 和 lower_price"}, ensure_ascii=False)
            
            # 获取当前价格
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            ticker = await client.get_ticker(symbol.upper())
            current_price = Decimal(str(ticker.get("lastPrice", 0))) if ticker else Decimal("0")
            
            bot = await GridStrategy.start_grid(
                db=db,
                user_id=user_id,
                symbol=symbol.upper(),
                upper_price=Decimal(str(upper_price)),
                lower_price=Decimal(str(lower_price)),
                grid_count=grid_count,
                investment=Decimal(str(investment)),
                leverage=leverage,
                current_price=current_price,
            )
            await db.commit()
            
            return json.dumps({
                "action": "started",
                "grid_id": bot.id,
                "symbol": bot.symbol,
                "upper_price": str(bot.upper_price),
                "lower_price": str(bot.lower_price),
                "grid_count": bot.grid_count,
                "investment": str(bot.investment),
                "message": f"网格 {bot.name} 已启动",
            }, ensure_ascii=False, default=str)
        
        elif action == "stop":
            if grid_id <= 0:
                return json.dumps({"error": "必须提供 grid_id"}, ensure_ascii=False)
            
            bot = await GridStrategy.stop_grid(db=db, grid_id=grid_id, user_id=user_id)
            await db.commit()
            
            return json.dumps({
                "action": "stopped",
                "grid_id": bot.id,
                "message": f"网格 {bot.name} 已停止",
            }, ensure_ascii=False, default=str)
        
        elif action == "delete":
            if grid_id <= 0:
                return json.dumps({"error": "必须提供 grid_id"}, ensure_ascii=False)
            
            from app.models.grid_bot import GridBot, GridStatus
            bot = await db.get(GridBot, grid_id)
            if not bot or bot.user_id != user_id:
                return json.dumps({"error": "网格不存在"}, ensure_ascii=False)
            if bot.status not in (GridStatus.STOPPED, GridStatus.CREATED, GridStatus.COMPLETED):
                return json.dumps({"error": "只能删除已停止的网格"}, ensure_ascii=False)
            
            await db.delete(bot)
            await db.commit()
            return json.dumps({
                "action": "deleted",
                "grid_id": grid_id,
                "message": "网格已删除",
            }, ensure_ascii=False)
        
        else:
            return json.dumps({
                "error": f"未知操作: {action}",
                "valid_actions": ["list", "start", "stop", "delete"],
            }, ensure_ascii=False)
    
    except Exception as e:
        logger.error(f"[AgentTools] manage_grid failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def get_trade_journal(
    db: AsyncSession,
    user_id: int,
    source: str = "",
    result_filter: str = "",
    limit: int = 20,
) -> str:
    """
    查询交易日记
    
    可选过滤:
    - source: agent / autopilot / quant / grid / manual (空=全部)
    - result_filter: win / loss (空=全部)
    - limit: 返回条数 (默认20)
    """
    from app.models.strategy import TradeMemory
    from sqlalchemy import desc
    
    try:
        query = select(TradeMemory).where(
            TradeMemory.user_id == user_id
        )
        
        if source:
            query = query.where(TradeMemory.source == source.lower())
        
        if result_filter == "win":
            query = query.where(TradeMemory.pnl_usdt > 0)
        elif result_filter == "loss":
            query = query.where(TradeMemory.pnl_usdt <= 0)
        
        query = query.order_by(desc(TradeMemory.created_at)).limit(limit)
        
        result = await db.execute(query)
        trades = result.scalars().all()
        
        trade_list = []
        total_pnl = 0.0
        wins = 0
        losses = 0
        
        for t in trades:
            pnl = float(t.pnl_usdt) if t.pnl_usdt else 0
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            
            trade_list.append({
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "source": t.source,
                "strategy_name": t.strategy_name,
                "entry_price": round(float(t.entry_price), 6) if t.entry_price else None,
                "exit_price": round(float(t.exit_price), 6) if t.exit_price else None,
                "leverage": t.leverage,
                "margin_used": round(float(t.margin_used), 2) if t.margin_used else None,
                "trade_result": t.trade_result,
                "pnl_usdt": round(pnl, 4),
                "pnl_pct": round(float(t.pnl_pct), 2) if t.pnl_pct else 0,
                "commission": round(float(t.commission), 4) if t.commission else 0,
                "duration_minutes": t.duration_minutes,
                "close_reason": t.close_reason,
                "had_stop_loss": t.had_stop_loss,
                "had_take_profit": t.had_take_profit,
                "open_reason": t.open_reason,
                "lesson": t.lesson,
                "situation": t.situation,
                "what_went_right": t.what_went_right,
                "what_went_wrong": t.what_went_wrong,
                "closed_at": t.created_at.isoformat() + "Z" if t.created_at else None,
            })
        
        win_rate = round(wins / len(trades) * 100, 1) if trades else 0
        
        return json.dumps({
            "count": len(trade_list),
            "summary": {
                "total_pnl": round(total_pnl, 4),
                "wins": wins,
                "losses": losses,
                "win_rate": f"{win_rate}%",
            },
            "trades": trade_list,
        }, ensure_ascii=False, default=str)
    
    except Exception as e:
        logger.error(f"[AgentTools] get_trade_journal failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 自动交易管理工具 ====================


@register_tool
async def start_autopilot(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
):
    """
    启动策略自动交易

    参数:
        strategy_id: 策略 ID (数字)。如果为空则启动所有活跃策略

    说明:
        启动后 autopilot 调度器会自动按策略设定的周期运行评估:
        获取行情 → 评估策略信号 → AI 审核 → Pipeline 风控 → 执行
        每次周期的决策过程会完整记录到决策日志中。
    """
    from app.services.agent.autopilot import autopilot

    try:
        if strategy_id:
            # 启动指定策略
            sid = int(strategy_id)
            result = await db.execute(
                select(Strategy).where(
                    Strategy.id == sid,
                    Strategy.user_id == user_id,
                )
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return json.dumps({"error": f"策略 ID {sid} 不存在"}, ensure_ascii=False)

            strategy.is_active = True
            await db.commit()

            # 如果 autopilot 未运行，立即启动
            if not autopilot.is_running(user_id):
                config = {
                    "symbols": [strategy.symbol],
                    "interval": strategy.interval,
                    "intervals": [strategy.interval],
                    "strategy_ids": [strategy.id],
                }
                await autopilot.start(user_id, config)

            return json.dumps({
                "action": "started",
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "symbol": strategy.symbol,
                "interval": strategy.interval,
                "message": f"策略 '{strategy.name}' 自动交易已启动",
            }, ensure_ascii=False)

        else:
            # 启动所有活跃策略
            result = await db.execute(
                select(Strategy).where(
                    Strategy.user_id == user_id,
                    Strategy.is_active == True,
                )
            )
            active = result.scalars().all()
            if not active:
                return json.dumps({"error": "没有活跃的策略，请先启动一个策略"}, ensure_ascii=False)

            if not autopilot.is_running(user_id):
                symbols = list(set(s.symbol for s in active))
                intervals = list(set(s.interval for s in active))
                config = {
                    "symbols": symbols,
                    "interval": intervals[0],
                    "intervals": intervals,
                    "strategy_ids": [s.id for s in active],
                }
                await autopilot.start(user_id, config)

            return json.dumps({
                "action": "started",
                "strategies": [{"id": s.id, "name": s.name} for s in active],
                "message": f"已启动 {len(active)} 个策略的自动交易",
            }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def stop_autopilot(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
):
    """
    停止自动交易

    参数:
        strategy_id: 策略 ID (可选)。如果为空则停止所有自动交易
    """
    from app.services.agent.autopilot import autopilot

    try:
        if strategy_id:
            sid = int(strategy_id)
            result = await db.execute(
                select(Strategy).where(
                    Strategy.id == sid,
                    Strategy.user_id == user_id,
                )
            )
            strategy = result.scalar_one_or_none()
            if strategy:
                strategy.is_active = False
                await db.commit()
                return json.dumps({
                    "action": "stopped",
                    "strategy_id": sid,
                    "message": f"策略 '{strategy.name}' 已停止",
                }, ensure_ascii=False)
            return json.dumps({"error": f"策略 ID {sid} 不存在"}, ensure_ascii=False)
        else:
            await autopilot.stop(user_id)
            # 标记所有策略为非活跃
            result = await db.execute(
                select(Strategy).where(
                    Strategy.user_id == user_id,
                    Strategy.is_active == True,
                )
            )
            for s in result.scalars().all():
                s.is_active = False
            await db.commit()
            return json.dumps({
                "action": "stopped",
                "message": "所有自动交易已停止",
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def get_autopilot_status(
    db: AsyncSession,
    user_id: int,
):
    """
    查询自动交易运行状态

    返回:
        运行状态、监控交易对、运行时长、周期次数、执行操作数
    """
    from app.services.agent.autopilot import autopilot

    status = autopilot.get_status(user_id)

    # 获取活跃策略列表
    result = await db.execute(
        select(Strategy).where(
            Strategy.user_id == user_id,
            Strategy.is_active == True,
        )
    )
    active = result.scalars().all()
    status["active_strategies"] = [
        {"id": s.id, "name": s.name, "symbol": s.symbol}
        for s in active
    ]

    return json.dumps(status, ensure_ascii=False, default=str)


@register_tool
async def get_trading_logs(
    db: AsyncSession,
    user_id: int,
    symbol: str = "",
    limit: int = 10,
):
    """
    查看最近的自动交易决策日志

    参数:
        symbol: 可选，过滤交易对
        limit: 返回条数 (默认 10)

    返回:
        每条日志包含: 时间、交易对、策略名、决策、AI思考摘要、是否执行
    """
    from app.models.autopilot_log import AutopilotLog

    try:
        query = (
            select(AutopilotLog)
            .where(AutopilotLog.user_id == user_id)
        )
        if symbol:
            query = query.where(AutopilotLog.symbol == symbol)
        query = query.order_by(AutopilotLog.created_at.desc()).limit(int(limit))

        result = await db.execute(query)
        logs = result.scalars().all()

        log_list = []
        for l in logs:
            log_list.append({
                "id": l.id,
                "time": l.created_at.isoformat() + "Z" if l.created_at else None,
                "symbol": l.symbol,
                "strategy": l.strategy_name,
                "decision": l.decision,
                "summary": l.summary,
                "action_taken": l.action_taken,
                "order_id": l.order_id,
            })

        return json.dumps({
            "count": len(log_list),
            "logs": log_list,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 趋势分析工具 ====================


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
            return json.dumps({"error": "没有活跃的趋势分析方案，请先创建或初始化预置方案"}, ensure_ascii=False)

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
                return json.dumps({"error": "获取行情失败"}, ensure_ascii=False)

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
        from datetime import datetime
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
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


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
            return json.dumps({"error": "没有活跃的趋势分析方案"}, ensure_ascii=False)

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

        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 新闻工具 ====================


@register_tool
async def get_news(
    db: AsyncSession,
    user_id: int,
    currency: str = "BTC",
    limit: int = 10,
) -> str:
    """
    查询最新加密货币新闻

    参数:
        currency: 币种过滤, 如 BTC / ETH / SOL (空=全部)
        limit: 返回条数 (默认10, 最大50)

    返回:
        新闻列表 (标题、中文标题、情绪、重要性、来源、时间)
    """
    from app.services.news.service import get_latest_news

    try:
        articles = await get_latest_news(
            db,
            currency=currency if currency else None,
            limit=min(limit, 50),
        )

        if not articles:
            return json.dumps({"message": f"暂无 {currency} 相关新闻"}, ensure_ascii=False)

        result = []
        for a in articles[:limit]:
            result.append({
                "title": a.get("title", ""),
                "title_zh": a.get("title_zh", ""),
                "sentiment": a.get("sentiment", "unknown"),
                "sentiment_score": a.get("sentiment_score"),
                "importance": a.get("importance", ""),
                "source": a.get("source", ""),
                "published_at": a.get("published_at", ""),
            })

        return json.dumps({
            "currency": currency,
            "count": len(result),
            "articles": result,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def get_market_sentiment(
    db: AsyncSession,
    user_id: int,
    currency: str = "BTC",
) -> str:
    """
    查询市场情绪 (基于新闻情感分析)

    参数:
        currency: 币种, 如 BTC / ETH (空=全部)

    返回:
        整体情绪(看多/看空/中性)、情绪分数、正面/负面/中性新闻数量
    """
    from app.services.news.service import get_market_sentiment as _get_sentiment

    try:
        sentiment = await _get_sentiment(
            db,
            currency=currency if currency else None,
            hours=24,
        )

        overall = sentiment.get("overall", "neutral")
        overall_zh = {"positive": "看多", "negative": "看空", "neutral": "中性"}.get(overall, overall)

        return json.dumps({
            "currency": currency,
            "overall": overall_zh,
            "score": sentiment.get("score", 0),
            "total_articles": sentiment.get("total_articles", 0),
            "positive_count": sentiment.get("positive_count", 0),
            "negative_count": sentiment.get("negative_count", 0),
            "neutral_count": sentiment.get("neutral_count", 0),
            "by_category": sentiment.get("by_category", {}),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 新闻监控规则工具 ====================


@register_tool
async def list_alerts(
    db: AsyncSession,
    user_id: int,
) -> str:
    """
    查看所有新闻监控规则

    返回:
        监控规则列表 (名称、关键词、触发次数、胜率、总盈亏)
    """
    from app.services.news.service import get_user_alerts, _alert_to_dict

    try:
        alerts = await get_user_alerts(db, user_id=user_id)

        if not alerts:
            return json.dumps({"message": "暂无监控规则，可使用 create_alert 创建"}, ensure_ascii=False)

        result = []
        for a in alerts:
            result.append({
                "id": a["id"],
                "name": a["name"],
                "keywords": a["keywords"],
                "action": a["action"],
                "is_active": a["is_active"],
                "trade_symbol": a.get("trade_symbol"),
                "trade_side": a.get("trade_side"),
                "triggered_count": a["triggered_count"],
                "win_count": a["win_count"],
                "loss_count": a["loss_count"],
                "win_rate": a["win_rate"],
                "total_pnl": a["total_pnl"],
            })

        return json.dumps({
            "count": len(result),
            "alerts": result,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def create_alert(
    db: AsyncSession,
    user_id: int,
    name: str = "",
    keywords: str = "",
    action: str = "notify",
    trade_symbol: str = "BTCUSDT",
    trade_side: str = "auto",
    trade_position_pct: float = 5.0,
    trade_leverage: int = 5,
    trade_stop_loss_pct: float = 2.0,
    trade_take_profit_pct: float = 3.0,
    news_categories: str = "",
    currencies: str = "",
    sentiment_filter: str = "any",
) -> str:
    """
    创建新闻监控规则

    参数:
        name: 规则名称, 如 "ETF利好做多"
        keywords: 关键词列表, 逗号分隔, 如 "ETF,BlackRock,降息"
        action: 动作类型, notify=仅通知, trade=自动交易
        trade_symbol: 交易对 (action=trade时生效)
        trade_side: 交易方向, buy/sell/auto (auto=根据新闻情感自动判断)
        trade_position_pct: 仓位比例% (1-15)
        trade_leverage: 杠杆倍数 (1-20)
        trade_stop_loss_pct: 止损百分比
        trade_take_profit_pct: 止盈百分比
        news_categories: 可选, 分类过滤, 逗号分隔 (macro/etf/regulation/exchange/whale/project)
        currencies: 可选, 币种过滤, 逗号分隔 (BTC/ETH/SOL)
        sentiment_filter: 情感过滤, any/positive/negative

    返回:
        创建成功的规则详情
    """
    from app.models.news import NewsAlert
    from app.services.news.service import get_user_alerts, _alert_to_dict

    try:
        if not name:
            return json.dumps({"error": "请提供规则名称 (name)"}, ensure_ascii=False)
        if not keywords:
            return json.dumps({"error": "请提供关键词 (keywords), 逗号分隔"}, ensure_ascii=False)

        # 检查规则数量限制
        existing = await get_user_alerts(db, user_id=user_id)
        if len(existing) >= 20:
            return json.dumps({"error": "监控规则已达上限 (20条)"}, ensure_ascii=False)

        # 解析逗号分隔的列表
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        cat_list = [c.strip() for c in news_categories.split(",") if c.strip()] if news_categories else None
        cur_list = [c.strip().upper() for c in currencies.split(",") if c.strip()] if currencies else None

        # 验证 trade 模式参数
        if action == "trade" and not trade_symbol:
            return json.dumps({"error": "交易模式需要指定 trade_symbol"}, ensure_ascii=False)

        alert = NewsAlert(
            user_id=user_id,
            name=name,
            keywords=kw_list,
            news_categories=cat_list,
            currencies=cur_list,
            sentiment_filter=sentiment_filter,
            action=action,
            trade_side=trade_side if action == "trade" else None,
            trade_symbol=trade_symbol if action == "trade" else None,
            trade_position_pct=trade_position_pct if action == "trade" else None,
            trade_leverage=trade_leverage if action == "trade" else None,
            trade_stop_loss_pct=trade_stop_loss_pct if action == "trade" else None,
            trade_take_profit_pct=trade_take_profit_pct if action == "trade" else None,
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)

        result = _alert_to_dict(alert)
        return json.dumps({
            "message": f"监控规则 '{name}' 创建成功",
            "alert": result,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def update_alert(
    db: AsyncSession,
    user_id: int,
    alert_id: int = 0,
    action: str = "",
    name: str = "",
    keywords: str = "",
    is_active: str = "",
    trade_side: str = "",
    trade_symbol: str = "",
    trade_position_pct: float = 0,
    trade_leverage: int = 0,
    trade_stop_loss_pct: float = 0,
    trade_take_profit_pct: float = 0,
) -> str:
    """
    修改/启停/删除新闻监控规则

    参数:
        alert_id: 规则 ID (必填)
        action: 操作类型
            - update: 修改规则 (默认)
            - activate: 启用规则
            - deactivate: 暂停规则
            - delete: 删除规则
        name: 新名称 (空=不修改)
        keywords: 新关键词, 逗号分隔 (空=不修改)
        is_active: "true"/"false" (空=不修改)
        trade_side: buy/sell/auto (空=不修改)
        trade_symbol: 交易对 (空=不修改)
        trade_position_pct: 仓位比例% (0=不修改)
        trade_leverage: 杠杆倍数 (0=不修改)
        trade_stop_loss_pct: 止损% (0=不修改)
        trade_take_profit_pct: 止盈% (0=不修改)

    返回:
        更新后的规则详情
    """
    from sqlalchemy import select as sa_select
    from app.models.news import NewsAlert
    from app.services.news.service import _alert_to_dict

    try:
        if alert_id <= 0:
            return json.dumps({"error": "请提供规则 ID (alert_id)"}, ensure_ascii=False)

        result = await db.execute(
            sa_select(NewsAlert).where(
                NewsAlert.id == alert_id,
                NewsAlert.user_id == user_id,
            )
        )
        alert = result.scalar_one_or_none()
        if not alert:
            return json.dumps({"error": f"规则 #{alert_id} 不存在"}, ensure_ascii=False)

        # 删除操作
        if action == "delete":
            alert_name = alert.name
            await db.delete(alert)
            await db.commit()
            return json.dumps({"message": f"规则 '{alert_name}' 已删除"}, ensure_ascii=False)

        # 快捷启停
        if action == "activate":
            alert.is_active = True
            await db.commit()
            return json.dumps({"message": f"规则 '{alert.name}' 已启用"}, ensure_ascii=False)
        if action == "deactivate":
            alert.is_active = False
            await db.commit()
            return json.dumps({"message": f"规则 '{alert.name}' 已暂停"}, ensure_ascii=False)

        # 逐字段更新
        if name:
            alert.name = name
        if keywords:
            alert.keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        if is_active:
            alert.is_active = is_active.lower() == "true"
        if trade_side:
            alert.trade_side = trade_side
        if trade_symbol:
            alert.trade_symbol = trade_symbol
        if trade_position_pct > 0:
            alert.trade_position_pct = trade_position_pct
        if trade_leverage > 0:
            alert.trade_leverage = trade_leverage
        if trade_stop_loss_pct > 0:
            alert.trade_stop_loss_pct = trade_stop_loss_pct
        if trade_take_profit_pct > 0:
            alert.trade_take_profit_pct = trade_take_profit_pct

        await db.commit()
        await db.refresh(alert)

        return json.dumps({
            "message": f"规则 '{alert.name}' 已更新",
            "alert": _alert_to_dict(alert),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 新闻-市场关联分析工具 ====================


@register_tool
async def analyze_news_impact(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    days: int = 30,
    window_hours: str = "1,4,24",
) -> str:
    """
    分析新闻对市场的影响 — 发现新闻-价格关联规律

    对过去N天的新闻，计算新闻发布后的价格变化，按分类/情感分组统计，
    找出"哪类新闻发生后市场如何反应"的规律。

    参数:
        symbol: 交易对 (默认 BTCUSDT)
        days: 回看天数 (默认30, 最大90)
        window_hours: 观察窗口, 逗号分隔 (默认 "1,4,24" 表示1h/4h/24h后的涨跌)

    返回:
        各分类/情感组合下的平均涨跌幅、胜率、样本数, 以及发现的规律总结
    """
    from sqlalchemy import select as sa_select, and_
    from app.models.news import NewsArticle
    from app.models.market import Kline
    from datetime import datetime, timedelta, timezone

    try:
        days = min(days, 90)
        windows = [int(h.strip()) for h in window_hours.split(",") if h.strip()]
        if not windows:
            windows = [1, 4, 24]

        cutoff = utc_now() - timedelta(days=days)

        # 1. 查询有 currency 标签的新闻
        news_result = await db.execute(
            sa_select(NewsArticle).where(
                NewsArticle.published_at >= cutoff,
            ).order_by(NewsArticle.published_at.desc()).limit(500)
        )
        articles = news_result.scalars().all()

        if not articles:
            return json.dumps({
                "message": f"过去 {days} 天没有新闻数据，无法分析",
            }, ensure_ascii=False)

        # 2. 对每条新闻，获取发布时 + 各窗口后的价格
        base_symbol = symbol.upper()
        impact_records = []

        for article in articles:
            pub_ts = int(article.published_at.timestamp() * 1000)

            # 获取新闻发布时的1h K线 (作为基准价)
            base_kline = await db.execute(
                sa_select(Kline).where(
                    and_(
                        Kline.symbol == base_symbol,
                        Kline.interval == "1h",
                        Kline.open_time <= pub_ts,
                    )
                ).order_by(Kline.open_time.desc()).limit(1)
            )
            base_k = base_kline.scalar_one_or_none()
            if not base_k:
                continue

            base_price = float(base_k.close)
            if base_price <= 0:
                continue

            # 各窗口后的价格变化
            changes = {}
            for w in windows:
                target_ts = pub_ts + w * 3600 * 1000
                future_kline = await db.execute(
                    sa_select(Kline).where(
                        and_(
                            Kline.symbol == base_symbol,
                            Kline.interval == "1h",
                            Kline.open_time <= target_ts,
                        )
                    ).order_by(Kline.open_time.desc()).limit(1)
                )
                future_k = future_kline.scalar_one_or_none()
                if future_k:
                    future_price = float(future_k.close)
                    pct_change = ((future_price - base_price) / base_price) * 100
                    changes[f"{w}h"] = round(pct_change, 3)

            if not changes:
                continue

            impact_records.append({
                "title": article.title[:60],
                "category": article.news_category or "other",
                "sentiment": article.sentiment or "neutral",
                "importance": article.importance or "low",
                "published_at": str(article.published_at),
                "base_price": base_price,
                "changes": changes,
            })

        if not impact_records:
            return json.dumps({
                "message": f"有 {len(articles)} 条新闻但无法匹配到 {base_symbol} K线数据",
            }, ensure_ascii=False)

        # 3. 按 (category, sentiment) 分组统计
        from collections import defaultdict
        groups = defaultdict(list)
        for rec in impact_records:
            key = f"{rec['category']}|{rec['sentiment']}"
            groups[key].append(rec)

        # 4. 计算统计指标
        group_stats = []
        for key, records in groups.items():
            category, sentiment = key.split("|")
            sample_count = len(records)
            if sample_count < 2:
                continue

            stats_entry = {
                "category": category,
                "sentiment": sentiment,
                "sample_count": sample_count,
            }

            for w in windows:
                w_key = f"{w}h"
                changes_in_window = [r["changes"].get(w_key) for r in records if w_key in r["changes"]]
                if not changes_in_window:
                    continue

                avg_change = sum(changes_in_window) / len(changes_in_window)
                positive_count = sum(1 for c in changes_in_window if c > 0)
                win_rate = positive_count / len(changes_in_window) * 100
                max_up = max(changes_in_window)
                max_down = min(changes_in_window)

                stats_entry[f"{w_key}_avg_change"] = round(avg_change, 3)
                stats_entry[f"{w_key}_win_rate"] = round(win_rate, 1)
                stats_entry[f"{w_key}_max_up"] = round(max_up, 2)
                stats_entry[f"{w_key}_max_down"] = round(max_down, 2)
                stats_entry[f"{w_key}_samples"] = len(changes_in_window)

            group_stats.append(stats_entry)

        # 按 4h 平均涨幅排序
        sort_key = "4h_avg_change" if "4h" in windows else f"{windows[0]}h_avg_change"
        group_stats.sort(key=lambda x: abs(x.get(sort_key, 0)), reverse=True)

        # 5. 发现规律 (显著模式)
        patterns = []
        for s in group_stats:
            for w in windows:
                w_key = f"{w}h"
                avg = s.get(f"{w_key}_avg_change", 0)
                wr = s.get(f"{w_key}_win_rate", 50)
                samples = s.get(f"{w_key}_samples", 0)
                if samples < 3:
                    continue

                if avg > 0.5 and wr >= 60:
                    patterns.append({
                        "rule": f"{s['category']}类 + {s['sentiment']}情感 → {w}h后平均涨{avg:.2f}%",
                        "direction": "做多",
                        "avg_change": avg,
                        "win_rate": wr,
                        "confidence": "高" if (samples >= 5 and wr >= 70) else "中",
                        "category": s["category"],
                        "sentiment": s["sentiment"],
                        "window": w,
                        "samples": samples,
                    })
                elif avg < -0.5 and wr <= 40:
                    real_wr = 100 - wr  # 做空胜率
                    patterns.append({
                        "rule": f"{s['category']}类 + {s['sentiment']}情感 → {w}h后平均跌{abs(avg):.2f}%",
                        "direction": "做空",
                        "avg_change": avg,
                        "win_rate": real_wr,
                        "confidence": "高" if (samples >= 5 and real_wr >= 70) else "中",
                        "category": s["category"],
                        "sentiment": s["sentiment"],
                        "window": w,
                        "samples": samples,
                    })

        patterns.sort(key=lambda x: abs(x["avg_change"]), reverse=True)

        return json.dumps({
            "symbol": base_symbol,
            "analysis_period": f"过去{days}天",
            "total_news": len(articles),
            "matched_news": len(impact_records),
            "windows": [f"{w}h" for w in windows],
            "group_stats": group_stats[:15],
            "discovered_patterns": patterns[:10],
            "hint": "使用 auto_generate_alerts 可将发现的规律自动创建为监控规则",
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def auto_generate_alerts(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    days: int = 30,
    min_win_rate: float = 60.0,
    min_samples: int = 3,
    action: str = "notify",
    trade_position_pct: float = 5.0,
    trade_leverage: int = 3,
    trade_stop_loss_pct: float = 2.0,
    trade_take_profit_pct: float = 4.0,
) -> str:
    """
    根据历史新闻-市场关联分析, 自动生成监控规则

    先运行 analyze_news_impact 发现规律, 然后对胜率超过阈值的模式自动创建 Alert。

    参数:
        symbol: 交易对 (默认 BTCUSDT)
        days: 分析回看天数 (默认30)
        min_win_rate: 最低胜率阈值% (默认60, 低于此值不创建)
        min_samples: 最少样本数 (默认3)
        action: 规则动作, notify=仅通知, trade=自动交易
        trade_position_pct: 仓位% (action=trade时)
        trade_leverage: 杠杆 (action=trade时)
        trade_stop_loss_pct: 止损% (action=trade时)
        trade_take_profit_pct: 止盈% (action=trade时)

    返回:
        自动创建的规则列表
    """
    from app.models.news import NewsAlert
    from app.services.news.service import get_user_alerts

    try:
        # 1. 先运行分析
        analysis_result = await analyze_news_impact(
            db=db,
            user_id=user_id,
            symbol=symbol,
            days=days,
            window_hours="1,4,24",
        )
        analysis = json.loads(analysis_result)

        if "error" in analysis:
            return json.dumps({"error": analysis["error"]}, ensure_ascii=False)

        patterns = analysis.get("discovered_patterns", [])
        if not patterns:
            return json.dumps({
                "message": f"过去{days}天未发现显著的新闻-市场关联规律 (需要更多数据)",
                "total_news_analyzed": analysis.get("total_news", 0),
            }, ensure_ascii=False)

        # 2. 检查已有规则数量
        existing = await get_user_alerts(db, user_id=user_id)
        remaining_slots = 20 - len(existing)
        if remaining_slots <= 0:
            return json.dumps({"error": "监控规则已达上限(20条), 请先删除旧规则"}, ensure_ascii=False)

        # 3. 按规则生成 Alert
        # 分类到关键词的映射
        category_keywords = {
            "macro": ["fed", "rate cut", "rate hike", "inflation", "CPI", "GDP", "FOMC", "联储", "降息", "加息"],
            "etf": ["ETF", "BlackRock", "Grayscale", "Fidelity", "inflow", "outflow", "spot ETF"],
            "regulation": ["SEC", "regulation", "lawsuit", "compliance", "ban", "license", "监管"],
            "exchange": ["Binance", "Coinbase", "listing", "delist", "exchange", "上币"],
            "whale": ["whale", "transfer", "wallet", "dormant", "accumulation", "巨鲸"],
            "project": ["upgrade", "fork", "mainnet", "partnership", "hack", "exploit", "airdrop"],
        }

        created_alerts = []
        for pattern in patterns:
            if len(created_alerts) >= remaining_slots:
                break

            win_rate = pattern.get("win_rate", 0)
            samples = pattern.get("samples", 0)

            if win_rate < min_win_rate or samples < min_samples:
                continue

            category = pattern["category"]
            sentiment = pattern["sentiment"]
            direction = pattern["direction"]
            avg_change = pattern["avg_change"]
            window = pattern.get("window", 4)

            # 生成规则名
            cat_zh = {
                "macro": "宏观", "etf": "ETF", "regulation": "监管",
                "exchange": "交易所", "whale": "巨鲸", "project": "项目",
            }.get(category, category)
            sent_zh = {"positive": "利好", "negative": "利空", "neutral": "中性"}.get(sentiment, sentiment)

            name = f"[AI发现] {cat_zh}{sent_zh}→{direction} ({win_rate:.0f}%胜率)"

            # 检查是否已存在同名规则
            if any(e.get("name") == name for e in existing):
                continue

            # 获取关键词
            keywords = category_keywords.get(category, [category])

            # 根据方向设置交易方向
            trade_side = "buy" if direction == "做多" else "sell"
            sentiment_filter = sentiment if sentiment != "neutral" else "any"

            alert = NewsAlert(
                user_id=user_id,
                name=name,
                keywords=keywords,
                news_categories=[category] if category != "other" else None,
                currencies=None,
                sentiment_filter=sentiment_filter,
                action=action,
                trade_side=trade_side if action == "trade" else None,
                trade_symbol=symbol if action == "trade" else None,
                trade_position_pct=trade_position_pct if action == "trade" else None,
                trade_leverage=trade_leverage if action == "trade" else None,
                trade_stop_loss_pct=trade_stop_loss_pct if action == "trade" else None,
                trade_take_profit_pct=trade_take_profit_pct if action == "trade" else None,
            )
            db.add(alert)
            await db.flush()

            created_alerts.append({
                "id": alert.id,
                "name": name,
                "category": category,
                "sentiment": sentiment,
                "direction": direction,
                "avg_change": f"{avg_change:+.2f}%",
                "win_rate": f"{win_rate:.0f}%",
                "samples": samples,
                "keywords": keywords[:5],
                "action": action,
            })

        if created_alerts:
            await db.commit()

        return json.dumps({
            "message": f"基于过去{days}天分析, 自动创建了 {len(created_alerts)} 条监控规则",
            "analysis_summary": {
                "total_news": analysis.get("total_news", 0),
                "matched_news": analysis.get("matched_news", 0),
                "patterns_found": len(patterns),
                "rules_created": len(created_alerts),
            },
            "created_alerts": created_alerts,
            "skipped_reason": f"跳过胜率<{min_win_rate}%或样本<{min_samples}的模式" if len(patterns) > len(created_alerts) else None,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
