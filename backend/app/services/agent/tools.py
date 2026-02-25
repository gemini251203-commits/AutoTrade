"""
Agent Tools
=============
AI 娴溿倖妲楁禒锝囨倞閻ㄥ嫬浼愰崗鐑芥肠

濮ｅ繋閲滃銉ュ徔閺勵垯绔存稉?async 閸戣姤鏆熼敍宀冪殶閻劎骞囬張澶婃倵缁旑垱婀囬崝鈥崇暚閹存劕鐤勯梽鍛惙娴ｆ嚎鈧?
瀹搞儱鍙块惃鍕翻閸忋儴绶崙娲厴閺勵垳鐣濋崡鏇犳畱 dict/str閿涘本鏌熸笟?AI 鐟欙絾鐎介妴?

閸涜棄鎮曠憴鍕瘱:
- 瀹搞儱鍙块崥? snake_case (娑?prompts.py 娑擃厾娈戝銉ュ徔閸氬秳绔存稉鈧€电懓绨?
- 閸欏倹鏆熼崥? snake_case (娑?API 鐏?DB 鐏炲倷绔撮懛?
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

# ==================== 閺夈儲绨稉濠佺瑓閺?====================
# Autopilot 鐠嬪啰鏁ら崜宥堫啎缂冾喗顒濋崣姗€鍣洪敍瀹紀ols 閼奉亜濮╂担璺ㄦ暏濮濓絿鈥橀惃?note 閸撳秶绱?
agent_source_var = contextvars.ContextVar('agent_source', default='agent')

# ==================== 瀹搞儱鍙垮▔銊ュ斀鐞?====================

TOOL_REGISTRY: Dict[str, Any] = {}


def register_tool(func):
    """濞夈劌鍞藉銉ュ徔閸掓澘鍙忕仦鈧▔銊ュ斀鐞?""
    TOOL_REGISTRY[func.__name__] = func
    return func


# ==================== 鐞涘本鍎忓銉ュ徔 ====================

@register_tool
async def get_price(db: AsyncSession, user_id: int, symbol: str = "BTCUSDT") -> str:
    """閺屻儴顕楃€圭偞妞傛禒閿嬬壐"""
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

    # Fallback: 娴犲孩鏆熼幑顔肩氨閼惧嘲褰?
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

    return json.dumps({"error": f"閺冪姵纭堕懢宄板絿 {symbol} 娴犻攱鐗?}, ensure_ascii=False)


@register_tool
async def get_funding_rate(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """
    閺屻儴顕楃挧鍕櫨鐠愬湱宸?閳?娴溿倖妲楅幋鎰拱閸掑棙鐎?

    閸欏倹鏆?
        symbol: 娴溿倖妲楃€? 婵?BTCUSDT / ETHUSDT

    鏉╂柨娲?
        瑜版挸澧犵拹鍦芳閵嗕礁鍕鹃崠鏍ㄥ灇閺堫兙鈧椒绗呭▎锛勭波缁犳妞傞梻娣偓浣割樋缁岀儤鏌熼崥鎴炲絹缁€?
    """
    from app.services.funding_rate import funding_rate_service
    info = await funding_rate_service.get_funding_info(symbol.upper())
    if info:
        return json.dumps(info, ensure_ascii=False)

    return json.dumps({"error": f"閺冪姵纭堕懢宄板絿 {symbol} 鐠у嫰鍣剧拹鍦芳"}, ensure_ascii=False)

@register_tool
async def get_klines(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    limit: int = 20,
) -> str:
    """閼惧嘲褰?K 缁炬寧鏆熼幑?""
    limit = min(int(limit), 50)  # 闂勬劕鍩楁潻鏂挎礀閺佷即鍣洪柆鍨帳 token 鏉╁洤顦?
    result = await db.execute(
        select(Kline)
        .where(Kline.symbol == symbol.upper(), Kline.interval == interval)
        .order_by(desc(Kline.open_time))
        .limit(limit)
    )
    klines = list(reversed(result.scalars().all()))

    if not klines:
        return json.dumps({"error": f"閺?{symbol} {interval} K缁炬寧鏆熼幑?}, ensure_ascii=False)

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


# ==================== 鐠愶附鍩涘銉ュ徔 ====================

@register_tool
async def get_balance(db: AsyncSession, user_id: int) -> str:
    """閺屻儴顕楃拹锔藉煕娴ｆ瑩顤?""
    result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = result.scalar_one_or_none()

    if not wallet:
        return json.dumps({"error": "闁藉崬瀵橀張顏勫灥婵瀵?}, ensure_ascii=False)

    return json.dumps({
        "available": float(wallet.balance),
        "frozen": float(wallet.frozen),
        "total_equity": float(wallet.total_equity),
        "total_pnl": float(wallet.total_pnl),
    }, ensure_ascii=False)


@register_tool
async def get_positions(db: AsyncSession, user_id: int) -> str:
    """閺屻儴顕楄ぐ鎾冲閹镐椒绮?""
    result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    positions = result.scalars().all()

    if not positions:
        return json.dumps({"positions": [], "message": "瑜版挸澧犻弮鐘冲瘮娴?}, ensure_ascii=False)

    # 閼惧嘲褰囩€圭偞妞傛禒閿嬬壐鐠侊紕鐣婚張顏勭杽閻滄壆娉╂禍?
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
    """閺屻儴顕楅幐鍌氬礋"""
    result = await db.execute(
        select(Order).where(
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN]),
        )
    )
    orders = result.scalars().all()

    if not orders:
        return json.dumps({"orders": [], "message": "瑜版挸澧犻弮鐘冲瘯閸?}, ensure_ascii=False)

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

# ==================== 娴溿倖妲楀銉ュ徔 ====================

# 缂佺喍绔撮崫浣侯潚缁狅紕鎮婇崳?(閺囧じ鍞弫锝堟儰閻?exchange_rules 鐎涙鍚€)
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
    """娑撳宕?(閸?Binance 鐟欏嫬鍨０鍕梾妤?"""
    from app.services.trading import OrderExecutor, OrderError

    try:
        symbol = symbol.upper()

        # ==================== 妫板嫭顥呮? Binance 娴溿倖妲楃憴鍕灟 ====================
        from app.services.exchange import BinanceClient
        client = BinanceClient()
        try:
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker.get("lastPrice", 0)) if ticker else 0
        except Exception:
            current_price = 0

        if current_price > 0:
            # 娴ｈ法鏁ょ紒鐔剁閸濅胶顫掔粻锛勬倞閸ｃ劑鐛欑拠?
            validation = security_manager.validate_order(symbol, quantity, current_price, leverage)
            if not validation["valid"]:
                return json.dumps({
                    "success": False,
                    "error": validation["error"],
                    "suggestion": validation["suggestion"],
                }, ensure_ascii=False)

            # 濡偓閺屻儰绻氱拠渚€鍣鹃弰顖氭儊婢?
            notional = quantity * current_price
            margin = notional / leverage if leverage > 0 else notional
            wallet_result = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallet = wallet_result.scalar_one_or_none()
            if wallet and margin > float(wallet.balance):
                available = float(wallet.balance)
                # 鐠侊紕鐣诲楦款唴閻ㄥ嫪鎱ㄥ锝呭棘閺?
                safe_margin = available * 0.3  # 娴ｈ法鏁?0%閸欘垳鏁ゆ担娆擃杺
                safe_notional = safe_margin * leverage
                safe_qty = safe_notional / current_price
                # 閹稿顒為梹鍨絿閺?
                safe_qty = float(security_manager.round_quantity_up(symbol, safe_qty))
                return json.dumps({
                    "success": False, 
                    "error": (
                        f"娣囨繆鐦夐柌鎴滅瑝鐡? 闂団偓鐟?${margin:,.2f} (閸氬秳绠?{notional:,.2f} / {leverage}x), "
                        f"娴ｅ棗褰查悽銊ょ稇妫版繀绮?${available:,.2f}閵?
                    ),
                    "suggested_fix": {
                        "quantity": safe_qty,
                        "leverage": leverage,
                        "margin": round(safe_margin, 2),
                        "notional": round(safe_notional, 2),
                    },
                    "hint": f"瀵ら缚顔呮担璺ㄦ暏 quantity={safe_qty}, leverage={leverage} 闁插秷鐦稉瀣礋閵?,
                }, ensure_ascii=False)

        # ==================== 闁俺绻冩０鍕梾妤? 閹笛嗩攽娑撳宕?====================
        order_side = OrderSide(side.lower())
        otype = OrderType(order_type.lower())
        order_price = Decimal(str(price)) if price and float(price) > 0 else None

        # 濮濄垺宕銏㈡畅閸欏倹鏆?
        sl = Decimal(str(stop_loss)) if stop_loss and float(stop_loss) > 0 else None
        tp = Decimal(str(take_profit)) if take_profit and float(take_profit) > 0 else None

        # 閺嶈宓侀弶銉︾爱娑撳﹣绗呴弬鍥┾€樼€?source
        source_label = agent_source_var.get('agent')

        # ==================== 闁俺绻?Pipeline 缂佺喍绔存稉瀣礋 ====================
        from app.core.pipeline import get_pipeline
        
        pipeline = get_pipeline(user_id)
        
        # 閼惧嘲褰囨担娆擃杺閸滃本瀵旀禒鎾蹭繆閹垳鏁ゆ禍搴棑閹?
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
            note=f"[{source_label.title()}] 娑撳宕?,
            available_balance=available_balance,
            total_equity=total_equity,
            open_positions=open_positions,
        )
        
        if result.get("success"):
            result["message"] = "鐠併垹宕熷鏌モ偓姘崇箖 Pipeline 閹笛嗩攽"
        
        return json.dumps(result, ensure_ascii=False)

    except OrderError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[AgentTools] place_order failed: {e}")
        return json.dumps({"success": False, "error": f"娑撳宕熸径杈Е: {str(e)}"}, ensure_ascii=False)


@register_tool
async def close_position(
    db: AsyncSession,
    user_id: int,
    position_id: int = 0,
    close_price: float = 0,
) -> str:
    """楠炲厖绮?""
    from app.services.trading import PositionManager, PositionError

    try:
        # PositionManager.close_position 閺?@staticmethod
        # 缁涙儳鎮? (db, position_id, close_price, close_quantity=None)
        # 鏉╂柨娲? (position, realized_pnl)
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
            "message": f"娴犳挷缍?#{position.id} 瀹告彃閽╂禒鎿勭礉閻╁牅绨?{float(realized_pnl):+.2f} USDT",
        }, ensure_ascii=False)

    except PositionError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[AgentTools] close_position failed: {e}")
        return json.dumps({"success": False, "error": f"楠炲厖绮ㄦ径杈Е: {str(e)}"}, ensure_ascii=False)


@register_tool
async def cancel_order(
    db: AsyncSession,
    user_id: int,
    order_id: int = 0,
) -> str:
    """閸欐牗绉风拋銏犲礋"""
    from app.services.trading import OrderExecutor, OrderError

    try:
        # OrderExecutor.cancel_order 閺?@staticmethod
        # 缁涙儳鎮? (db, order_id, user_id)
        order = await OrderExecutor.cancel_order(
            db=db,
            order_id=int(order_id),
            user_id=user_id,
        )

        return json.dumps({
            "success": True,
            "order_id": order.id,
            "symbol": order.symbol,
            "message": f"鐠併垹宕?#{order.id} 瀹告彃褰囧☉?,
        }, ensure_ascii=False)

    except OrderError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[AgentTools] cancel_order failed: {e}")
        return json.dumps({"success": False, "error": f"閸欐牗绉锋径杈Е: {str(e)}"}, ensure_ascii=False)


# ==================== 閸掑棙鐎藉銉ュ徔 ====================

@register_tool
async def get_indicators(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
) -> str:
    """閼惧嘲褰囬幎鈧張顖涘瘹閺?(婢х偛宸遍悧?閳?娴ｈ法鏁ょ€瑰本鏆ｉ幐鍥ㄧ垼鎼?"""
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
                    # 鏉烆剚宕叉稉?indicators.py 鐟曚焦鐪伴惃?kline dict 閺嶇厧绱?
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

                    # 鐠嬪啰鏁ょ€瑰本鏆ｉ幐鍥ㄧ垼鐠侊紕鐣?
                    indicators = calculate_all_indicators(klines)

                    # 閺嶇厧绱￠崠鏍翻閸?閳?閸欘亙绻氶悾娆忓彠闁款喗鏆熼幑顕嗙礉闁灝鍘ゆ潻鍥毐
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

                    # 閸掋倖鏌囩搾瀣◢
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

    return json.dumps({"error": f"閺冪姵纭堕懢宄板絿 {symbol} {interval} 閹稿洦鐖?}, ensure_ascii=False)


@register_tool
async def analyze_market(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """缂佺厧鎮庣敮鍌氭簚閸掑棙鐎?(鐠嬪啰鏁ゆ径姘閼虫垝缍?"""
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
        return json.dumps({"error": f"鐢倸婧€閸掑棙鐎芥径杈Е: {str(e)}"}, ensure_ascii=False)


@register_tool
async def query_memories(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
) -> str:
    """閺屻儴顕楁禍銈嗘鐠佹澘绻?(閹碘偓閺堝娼靛┃? 閹靛濮?AI/娣団€冲娇/闁插繐瀵?"""
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
            "message": f"閺嗗倹妫?{symbol} 閻ㄥ嫪姘﹂弰鎾诡唶韫?,
        }, ensure_ascii=False)

    source_labels = {
        "manual": "閹靛濮?, "agent": "AI Agent",
        "signal": "娣団€冲娇閸斺晜澧?, "quant": "闁插繐瀵茬粵鏍殣",
    }

    data = [
        {
            "symbol": m.symbol,
            "source": source_labels.get(m.source, m.source) if m.source else "閺堫亞鐓?,
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


# ==================== 缁涙牜鏆愮粻锛勬倞瀹搞儱鍙?====================


@register_tool
async def list_strategies(
    db: AsyncSession,
    user_id: int,
) -> str:
    """閸掓鍤幍鈧張澶婂讲閻劎鐡ラ悾?(閻劍鍩涢崚娑樼紦閻?+ 妫板嫯顔曞Ο鈩冩緲)"""
    from app.services.quant.strategy import list_templates

    # 1. 閻劍鍩涢懛顏勭箒閻ㄥ嫮鐡ラ悾?
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

    # 2. 妫板嫯顔曞Ο鈩冩緲
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
    """閺屻儳婀呯粵鏍殣鐠囷妇绮忛柊宥囩枂 (閺€顖涘瘮閻劍鍩涚粵鏍殣 ID 閹存牗膩閺?ID)"""
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES

    engine = StrategyEngine()

    # 鐏忔繆鐦担婊€璐熼弫鐗堝祦鎼?ID 閺屻儴顕?
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

    # 鐏忔繆鐦担婊€璐熷Ο鈩冩緲 ID 閺屻儴顕?
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

    return json.dumps({"error": f"閹靛彞绗夐崚鎵摜閻? {strategy_id}"}, ensure_ascii=False)


async def _fetch_klines_map(symbol: str, timeframes: list) -> dict:
    """
    閼惧嘲褰囨径姘闂傚瓨顢嬮弸?K 缁炬寧鏆熼幑?
    
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
                logger.warning(f"[Tools] 閼惧嘲褰?{tf} K缁惧灝銇戠拹? {e}")
    return klines_map


@register_tool
async def evaluate_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
    symbol: str = "",
) -> str:
    """
    鐠囧嫪鍙婄粵鏍殣閸︺劌缍嬮崜宥堫攽閹懍绗呴惃鍕繆閸?(娑撳秳绱版稉瀣礋)

    閸欏倹鏆?
        strategy_id: 閻劍鍩涚粵鏍殣 ID (閺佹澘鐡? 閹存牗膩閺?ID (鐎涙顑佹稉?
        symbol: 閸欘垶鈧? 鐟曞棛娲婄粵鏍殣姒涙顓婚惃鍕唉閺勬挸顕?
    """
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES

    engine = StrategyEngine()

    # 閼惧嘲褰囩粵鏍殣闁板秶鐤?
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
        return json.dumps({"error": f"閹靛彞绗夐崚鎵摜閻? {strategy_id}"}, ensure_ascii=False)

    # 婵″倹鐏夐幐鍥х暰娴?symbol閿涘矁顩惄鏍摜閻ｃ儵绮拋銈囨畱
    target_symbol = (symbol or config.get("symbol", "BTCUSDT")).upper()
    config["symbol"] = target_symbol

    # 閼惧嘲褰囨径姘闂傚瓨顢嬮弸?K 缁炬寧鏆熼幑?
    required_tfs = config.get("_required_timeframes", [config.get("interval", "1h")])
    
    try:
        klines_map = await _fetch_klines_map(target_symbol, required_tfs)
    except Exception as e:
        return json.dumps({"error": f"閼惧嘲褰嘖缁惧灝绱撶敮? {str(e)}"}, ensure_ascii=False)

    if not klines_map:
        return json.dumps({"error": "閺冪姵纭堕懢宄板絿娴犺缍嶉弮鍫曟？濡楀棙鐏﹂惃鍑ㄧ痪鎸庢殶閹?}, ensure_ascii=False)

    # 閹笛嗩攽缁涙牜鏆愮拠鍕強
    try:
        signal = engine.evaluate(config, klines_map=klines_map)
    except Exception as e:
        return json.dumps({"error": f"缁涙牜鏆愮拠鍕強婢惰精瑙? {str(e)}"}, ensure_ascii=False)

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
    鐎瑰本鏆ｉ幍褑顢戠粵鏍殣: 鐠囧嫪鍙?閳?妞嬪孩甯?閳?娑撳宕?

    閸欘亝婀佽ぐ鎾剁摜閻ｃ儰楠囬悽鐔峰弳閸﹁桨淇婇崣?AND 闁俺绻冩搴㈠付閺冭埖澧犳稉瀣礋閵?
    """
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES
    from app.services.risk.risk_model import RiskModel
    from app.services.trading.position_manager import PositionManager
    from app.services.quant.indicators import get_indicator

    engine = StrategyEngine()
    risk_guard = RiskModel()

    # 閼惧嘲褰囩粵鏍殣闁板秶鐤?
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
        return json.dumps({"error": f"閹靛彞绗夐崚鎵摜閻? {strategy_id}"}, ensure_ascii=False)

    target_symbol = (symbol or config.get("symbol", "BTCUSDT")).upper()
    config["symbol"] = target_symbol

    # 1. 閼惧嘲褰囨径姘闂傚瓨顢嬮弸?K 缁?
    required_tfs = config.get("_required_timeframes", [config.get("interval", "1h")])
    try:
        klines_map = await _fetch_klines_map(target_symbol, required_tfs)
    except Exception as e:
        return json.dumps({"error": f"閼惧嘲褰嘖缁惧灝绱撶敮? {str(e)}"}, ensure_ascii=False)

    if not klines_map:
        return json.dumps({"error": "閺冪姵纭堕懢宄板絿K缁炬寧鏆熼幑?}, ensure_ascii=False)

    # 閸欐牔瀵岄弮鍫曟？濡楀棙鐏?K 缁?(閻劋绨禒閿嬬壐閸?ATR)
    default_interval = config.get("interval", "1h")
    main_klines = klines_map.get(default_interval, list(klines_map.values())[0])

    # 2. 缁涙牜鏆愮拠鍕強
    try:
        signal = engine.evaluate(config, klines_map=klines_map)
    except Exception as e:
        return json.dumps({"error": f"缁涙牜鏆愮拠鍕強瀵倸鐖? {str(e)}"}, ensure_ascii=False)

    if not signal.has_signal:
        return json.dumps({
            "action": "no_signal",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": f"缁涙牜鏆?'{strategy_name}' 瑜版挸澧犻弮鐘辨唉閺勬挷淇婇崣?,
            "conditions_met": [str(c) for c in signal.conditions_met],
            "conditions_failed": [str(c) for c in signal.conditions_failed],
        }, ensure_ascii=False, default=str)

    if signal.signal_type.value == "exit":
        return json.dumps({
            "action": "exit_signal",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": f"缁涙牜鏆?'{strategy_name}' 瀵ら缚顔呴獮鍏呯波",
            "side": signal.side.value if signal.side else None,
            "conditions_met": [str(c) for c in signal.conditions_met],
        }, ensure_ascii=False, default=str)

    # 3. 閼惧嘲褰囬柦鍗炲瘶娴ｆ瑩顤傞崪灞惧瘮娴?(娓?Pipeline 妞嬪孩甯舵担璺ㄦ暏)
    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = wallet_result.scalar_one_or_none()
    wallet_balance = float(wallet.balance) if wallet else 0.0

    if wallet_balance <= 0:
        return json.dumps({"error": "闁藉崬瀵樻担娆擃杺娑撳秷鍐?}, ensure_ascii=False)

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

    # 4. 鐠侊紕鐣绘稉瀣礋閸欏倹鏆?
    risk_config = signal.risk_config
    current_price = Decimal(str(main_klines[-1]["close"]))
    leverage = risk_config.get("leverage", 1)
    position_pct = risk_config.get("position_pct", 10)

    # L4: 濞夈垹濮╅悳鍥殰闁倸绨叉禒鎾茬秴
    if risk_config.get("volatility_adjust"):
        try:
            atr_val = get_indicator("atr", main_klines)
            if atr_val and float(current_price) > 0:
                atr_pct = atr_val / float(current_price) * 100
                vol_factor = max(0.33, min(1.0, 1.0 / atr_pct))
                original_pct = position_pct
                position_pct = round(position_pct * vol_factor, 1)
                logger.info(
                    f"[Strategy] 濞夈垹濮╅悳鍥殶閺? ATR%={atr_pct:.2f}%, "
                    f"娴犳挷缍?{original_pct}% 閳?{position_pct}%"
                )
        except Exception as e:
            logger.warning(f"[Strategy] 濞夈垹濮╅悳鍥殶閺佹潙銇戠拹? {e}")

    trade_amount = wallet_balance * position_pct / 100
    quantity = Decimal(str(round(trade_amount / float(current_price), 4)))

    side_map = {"buy": PositionSide.LONG, "sell": PositionSide.SHORT}
    position_side = side_map.get(signal.side.value, PositionSide.LONG) if signal.side else PositionSide.LONG

    # 鐠侊紕鐣诲銏″疮濮濄垻娉?(L2: 閺€顖涘瘮閸斻劍鈧焦顒涢幑?
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

    # 5. 闁俺绻?Pipeline 缂佺喍绔存稉瀣礋 (Risk 閳?Execution)
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
                "message": f"缁涙牜鏆?'{strategy_name}' 瀹告煡鈧俺绻?Pipeline 閹笛嗩攽",
            }, ensure_ascii=False, default=str)
        else:
            return json.dumps({
                "action": "risk_blocked",
                "strategy_name": strategy_name,
                "symbol": target_symbol,
                "message": result.get("error", "Pipeline 閹笛嗩攽婢惰精瑙?),
                "signal": signal.summary(),
            }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"娑撳宕熸径杈Е: {str(e)}"}, ensure_ascii=False)


def _calc_fixed_stops(
    current_price: Decimal,
    position_side,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple:
    """鐠侊紕鐣婚崶鍝勭暰閻ф儳鍨庡В鏃€顒涢幑鐔割剾閻?""
    if position_side.value == "long":
        stop_loss = current_price * (1 - Decimal(str(stop_loss_pct)) / 100) if stop_loss_pct else None
        take_profit = current_price * (1 + Decimal(str(take_profit_pct)) / 100) if take_profit_pct else None
    else:
        stop_loss = current_price * (1 + Decimal(str(stop_loss_pct)) / 100) if stop_loss_pct else None
        take_profit = current_price * (1 - Decimal(str(take_profit_pct)) / 100) if take_profit_pct else None
    return stop_loss, take_profit


def _build_validation_report(config: dict) -> dict:
    """閻㈢喐鍨氱粵鏍殣妤犲矁鐦夐幎銉ユ啞 閳?鐠?AI 閸滃瞼鏁ら幋椋庘€樼拋銈囩摜閻ｃ儱鐤勯梽鍛瘶閸氼偂绮堟稊?""
    is_pipeline = any(k in config for k in ("alphas", "portfolio", "execution"))
    
    if is_pipeline:
        alphas = config.get("alphas", [])
        return {
            "is_pipeline": True,
            "alphas": len(alphas),
            "portfolio": config.get("portfolio", {}).get("type", "unknown"),
            "risk": config.get("risk", {}).get("type", "unknown"),
            "execution": config.get("execution", {}).get("type", "unknown"),
            "features": ["Pipeline閺嬭埖鐎?]
        }

    entry = config.get("entry", {})
    exit_block = config.get("exit", {})
    risk = config.get("risk", {})

    entry_conds = entry.get("conditions", [])
    exit_conds = exit_block.get("conditions", [])

    # 閺€鍫曟肠娴ｈ法鏁ら惃鍕瘹閺?
    indicators_used = set()
    for cond in entry_conds + exit_conds:
        if "indicator" in cond:
            indicators_used.add(cond["indicator"])
        if "reference" in cond:
            indicators_used.add(cond["reference"])

    # 閺€鍫曟肠娴ｈ法鏁ら惃鍕閼?
    features = []
    for cond in entry_conds + exit_conds:
        if "timeframe" in cond:
            features.append("婢舵碍妞傞梻瀛橆攱閺?)
        if "cross" in cond:
            features.append("閺冭泛绨粚鑳Ш")
        if "expression" in cond:
            features.append("閼奉亜鐣炬稊澶庛€冩潏鎯х础")
        if "weight" in cond:
            features.append("閺夊啴鍣哥拠鍕瀻")
    if config.get("scoring"):
        features.append(f"鐠囧嫬鍨庨梼鍫濃偓?{config['scoring'].get('min_score', '?')}")
    if config.get("stages"):
        features.append(f"閸掑棙澹掑杞扮波({len(config['stages'])}闂冭埖顔?")
    if config.get("time_filter"):
        features.append("閺冨爼妫挎潻鍥ㄦ姢")
    if risk.get("stop_type") and risk["stop_type"] != "fixed":
        features.append(f"閸斻劍鈧焦顒涢幑?{risk['stop_type']})")
    if risk.get("volatility_adjust"):
        features.append("濞夈垹濮╅悳鍥殰闁倸绨?)

    report = {
        "is_pipeline": False,
        "entry_conditions": len(entry_conds),
        "exit_conditions": len(exit_conds),
        "entry_operator": entry.get("operator", "AND"),
        "exit_operator": exit_block.get("operator", "OR"),
        "indicators_used": sorted(indicators_used),
        "risk_summary": {
            "side": risk.get("side", "閺堫亣顔曠純?),
            "leverage": risk.get("leverage", "閺堫亣顔曠純?),
            "position_pct": risk.get("position_pct", "閺堫亣顔曠純?),
            "stop_loss_pct": risk.get("stop_loss_pct", "閺堫亣顔曠純?),
            "take_profit_pct": risk.get("take_profit_pct", "閺堫亣顔曠純?),
            "stop_type": risk.get("stop_type", "fixed"),
        },
        "required_timeframes": config.get("_required_timeframes", []),
        "features": sorted(set(features)) if features else ["閸╄櫣顢呯粵鏍殣"],
    }

    # 鐠€锕€鎲?
    warnings = []
    if len(entry_conds) == 0:
        warnings.append("閳跨媴绗?濞屸剝婀侀崗銉ユ簚閺夆€叉")
    if len(exit_conds) == 0:
        warnings.append("閳跨媴绗?濞屸剝婀侀崙鍝勬簚閺夆€叉")
    if not risk.get("side"):
        warnings.append("閳跨媴绗?閺堫亣顔曠純?risk.side (buy/sell)")
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
    閸掓稑缂撻弬鎵摜閻ｃ儱鑻熸穱婵嗙摠閸掔増鏆熼幑顔肩氨

    閸欏倹鏆?
        name: 缁涙牜鏆愰崥宥囆?
        symbol: 娴溿倖妲楃€?
        interval: K 缁惧灝鎳嗛張?
        config_yaml: YAML 閺嶇厧绱￠惃鍕摜閻ｃ儵鍘ょ純?
    """
    from app.services.quant.strategy import StrategyEngine

    if not name or not config_yaml:
        return json.dumps({"error": "缂傚搫鐨箛鍛邦洣閸欏倹鏆? name 閸?config_yaml"}, ensure_ascii=False)

    engine = StrategyEngine()
    try:
        config = engine.parse_yaml(config_yaml)
    except ValueError as e:
        return json.dumps({"error": f"YAML 闁板秶鐤嗘宀冪槈婢惰精瑙? {str(e)}"}, ensure_ascii=False)

    # 瀵儤鐗庢宀嬬窗閺勵垰鎯佺€涙ê婀稉宥嗘暜閹镐胶娈戦幐鍥ㄧ垼
    report = _build_validation_report(config)
    if not report.get("is_valid", False):
        error_msgs = []
        if report.get("unknown_indicators"):
            error_msgs.append(f"娴ｈ法鏁ゆ禍鍡欓兇缂佺喍绗夐弨顖涘瘮閻ㄥ嫭瀵氶弽? {', '.join(report['unknown_indicators'])}")
        if report.get("syntax_errors"):
            error_msgs.extend(report["syntax_errors"])
        if error_msgs:
            return json.dumps({"error": f"缁涙牜鏆愰柊宥囩枂閺冪姵鏅? {'; '.join(error_msgs)}"}, ensure_ascii=False)

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
        "message": f"缁涙牜鏆?'{name}' 瀹告彃鍨卞?(ID: {strategy.id})閿涘矂绮拋銈嗘弓閸氼垳鏁?,
        "validation_report": report,
    }, ensure_ascii=False)


@register_tool
async def list_modules(
    db: AsyncSession,
    user_id: int,
    layer: str = "",
) -> str:
    """
    閺屻儴顕楅崣顖滄暏閻ㄥ嫮鐡ラ悾銉δ侀崸妤冩窗瑜?

    閸欏倹鏆?
        layer: 閹稿洤鐣剧仦?(alpha/portfolio/risk/execution)閿涘瞼鈹?閺勫墽銇氶崗銊╁劥

    鏉╂柨娲?
        閸氬嫬鐪伴崣顖滄暏濡€虫健濞撳懎宕熼敍灞芥儓閸欏倹鏆熺拠瀛樻
    """
    from app.services.quant.module_registry import list_modules as _list, get_registry_summary

    if layer and layer not in ("alpha", "portfolio", "risk", "execution"):
        return json.dumps({"error": f"閺堫亞鐓＄仦? {layer}閵嗗倸褰查柅? alpha/portfolio/risk/execution"}, ensure_ascii=False)

    modules = _list(layer or None)

    if not modules:
        return json.dumps({"error": f"鐏?'{layer}' 濞屸剝婀侀崣顖滄暏濡€虫健"}, ensure_ascii=False)

    result = []
    for m in modules:
        result.append(m.to_dict())

    summary = get_registry_summary()

    return json.dumps({
        "modules": result,
        "summary": summary,
        "hint": "娴ｈ法鏁?create_pipeline_strategy 閺冭绱濇禒搴㈢槨鐏炲倿鈧瀚ㄦ稉鈧稉顏吥侀崸妤€鑻熼柊宥囩枂閸欏倹鏆?,
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
    閸掓稑缂撴径姘侀崸妤佺ウ濮樺鍤庣粵鏍殣楠炴湹绻氱€涙ê鍩岄弫鐗堝祦鎼?

    閸欏倹鏆?
        name: 缁涙牜鏆愰崥宥囆?
        symbol: 娴溿倖妲楃€?
        interval: K 缁惧灝鎳嗛張?
        config_yaml: YAML 閺嶇厧绱￠惃?pipeline 缁涙牜鏆愰柊宥囩枂
    """
    from app.services.quant.strategy import StrategyEngine

    if not name or not config_yaml:
        return json.dumps({"error": "缂傚搫鐨箛鍛邦洣閸欏倹鏆? name 閸?config_yaml"}, ensure_ascii=False)

    engine = StrategyEngine()
    try:
        config = engine.parse_yaml(config_yaml)
    except ValueError as e:
        return json.dumps({"error": f"YAML 闁板秶鐤嗘宀冪槈婢惰精瑙? {str(e)}"}, ensure_ascii=False)

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
        "message": f"濞翠焦鎸夌痪璺ㄧ摜閻?'{name}' 瀹告彃鍨卞?(ID: {strategy.id})閿涘矂绮拋銈嗘弓閸氼垳鏁?,
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
    娣囶喗鏁煎鍙夋箒缁涙牜鏆愰柊宥囩枂

    閸欏倹鏆?
        strategy_id: 缁涙牜鏆?ID (閺佹澘鐡?
        name/symbol/interval/config_yaml: 鐟曚焦娲块弬鎵畱鐎涙顔?(缁屽搫鐡х粭锔胯鐞涖劎銇氭稉宥勬叏閺€?
    """
    from app.services.quant.strategy import StrategyEngine

    if not str(strategy_id).isdigit():
        return json.dumps({"error": f"閺冪姵鏅ラ惃鍕摜閻?ID: {strategy_id}"}, ensure_ascii=False)

    result = await db.execute(
        select(Strategy).where(
            Strategy.id == int(strategy_id),
            Strategy.user_id == user_id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return json.dumps({"error": f"閹靛彞绗夐崚鎵摜閻?ID: {strategy_id}"}, ensure_ascii=False)

    # 妤犲矁鐦夐弬鎵畱 YAML (婵″倹鐏夐幓鎰返娴?
    report = {}
    if config_yaml:
        engine = StrategyEngine()
        try:
            config = engine.parse_yaml(config_yaml)
        except ValueError as e:
            return json.dumps({"error": f"YAML 闁板秶鐤嗙憴锝嗙€芥径杈Е: {str(e)}"}, ensure_ascii=False)
        
        # 瀵儤鐗庢灞炬煀閻?YAML
        report = _build_validation_report(config)
        if not report.get("is_valid", False):
            error_msgs = []
            if report.get("unknown_indicators"):
                error_msgs.append(f"娴ｈ法鏁ゆ禍鍡欓兇缂佺喍绗夐弨顖涘瘮閻ㄥ嫭瀵氶弽? {', '.join(report['unknown_indicators'])}")
            if report.get("syntax_errors"):
                error_msgs.extend(report["syntax_errors"])
            if error_msgs:
                return json.dumps({"error": f"缁涙牜鏆愰柊宥囩枂閺冪姵鏅ラ弮鐘崇《閺囧瓨鏌? {'; '.join(error_msgs)}"}, ensure_ascii=False)
                
        strategy.config_yaml = config_yaml

    if name:
        strategy.name = name
    if symbol:
        strategy.symbol = symbol.upper()
    if interval:
        strategy.interval = interval

    await db.commit()

    await db.commit()

    # 婵″倹鐏夊▽鈩冨絹娓氭稒鏌婇惃?YAML閿涘瞼鏁撻幋鎰＋ YAML 閻ㄥ嫰鐛欑拠浣瑰Г閸?
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
        "message": f"缁涙牜鏆?'{strategy.name}' (ID: {strategy.id}) 瀹稿弶娲块弬?,
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
    婢舵艾鎳嗛張鐔荤Ъ閸斿灝鍨庨弸?閳?閸掑棗鍩嗛崷?15m/1h/4h/1d 閸ユ稐閲滈崨銊︽埂閸掋倖鏌囩搾瀣◢

    楠炶埖甯归懡鎰扳偓鍌氭値瑜版挸澧犵搾瀣◢閻ㄥ嫮鐡ラ悾銉ц閸?
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
            trends[tf] = {"trend": "unknown", "error": "閺佺増宓佹稉宥堝喕"}
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

        # 閸掋倖鏌囩搾瀣◢
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

    # 缂佺厧鎮庨崚銈嗘焽
    macro_trends = [trends.get(tf, {}).get("trend", "unknown") for tf in ["4h", "1d"]]
    micro_trends = [trends.get(tf, {}).get("trend", "unknown") for tf in ["15m", "1h"]]

    macro = "bullish" if macro_trends.count("bullish") >= 1 else \
            "bearish" if macro_trends.count("bearish") >= 1 else "neutral"
    micro = "bullish" if micro_trends.count("bullish") >= 1 else \
            "bearish" if micro_trends.count("bearish") >= 1 else "neutral"

    # 缁涙牜鏆愰幒銊ㄥ礃
    recommendations = []
    if macro == "bullish" and micro == "bullish":
        recommendations = ["鐡掑濞嶇捄鐔婚嚋缁涙牜鏆?(妞ゅ搫濞嶉崑姘樋)", "閸у洨鍤庨柌鎴濆级缁涙牜鏆?, "RSI 閸ョ偠鐨熸稊鏉垮弳"]
    elif macro == "bearish" and micro == "bearish":
        recommendations = ["鐡掑濞嶇捄鐔婚嚋缁涙牜鏆?(妞ゅ搫濞嶉崑姘扁敄)", "RSI 鐡掑懍鎷遍崑姘扁敄", "閸у洨鍤庡璇插级缁涙牜鏆?]
    elif macro == "bullish" and micro in ["neutral", "bearish"]:
        recommendations = ["闁澀缍嗘稊鏉垮弳缁涙牜鏆?, "RSI 鐡掑懎宕犻崣宥呰剨 (婢堆嗙Ъ閸旇法婀呭☉顭掔礉閻厽婀￠崶鐐剁殶)", "閺€顖涙嫼娴ｅ秴寮藉?]
    elif macro == "bearish" and micro in ["neutral", "bullish"]:
        recommendations = ["闁垽鐝崑姘扁敄缁涙牜鏆?, "闂冭濮忔担宥呭冀瀵懓浠涚粚?(婢堆嗙Ъ閸旇法婀呯捄宀嬬礉閻厽婀￠崣宥呰剨)"]
    else:
        recommendations = ["閸栨椽妫块棁鍥幢缁涙牜鏆?, "鐢啯鐏勭敮锔剧崐閻?, "缁涘绶熺搾瀣◢閺勫海鈥橀崘宥呭弳閸?]

    return json.dumps({
        "symbol": symbol.upper(),
        "macro_trend": macro,
        "micro_trend": micro,
        "timeframes": trends,
        "recommendations": recommendations,
    }, ensure_ascii=False, default=str)


# ==================== 娴溿倗顓告稉顓炵妇瀹搞儱鍙?====================

@register_tool
async def manage_autopilot(
    db: AsyncSession,
    user_id: int,
    action: str = "status",
    symbols: str = "BTCUSDT",
    interval: str = "15m",
) -> str:
    """
    缁狅紕鎮婇懛顏勫З娴溿倖妲?(AutoPilot)
    
    action 閸欘垶鈧?
    - status: 閺屻儴顕楄ぐ鎾冲閻樿埖鈧?
    - start: 閸氼垰濮╅懛顏勫З娴溿倖妲?
    - stop: 閸嬫粍顒涢懛顏勫З娴溿倖妲?
    - run_once: 閹靛濮╃憴锕€褰傛稉鈧▎鈥冲枀缁?
    - logs: 閺屻儳婀呴張鈧潻鎴炴）韫?
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
                "message": "AutoPilot 瀹告彃浠犲?,
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
                "error": f"閺堫亞鐓￠幙宥勭稊: {action}",
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
    缁狅紕鎮婄純鎴炵壐娴溿倖妲?
    
    action 閸欘垶鈧?
    - list: 閺屻儳婀呴幍鈧張澶岀秹閺嶅吋婧€閸ｃ劋姹?
    - start: 閸掓稑缂撻獮璺烘儙閸斻劎缍夐弽?(闂団偓鐟?symbol/upper_price/lower_price/grid_count/investment)
    - stop: 閸嬫粍顒涚純鎴炵壐 (闂団偓鐟?grid_id)
    - delete: 閸掔娀娅庣純鎴炵壐 (闂団偓鐟?grid_id)
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
                return json.dumps({"error": "韫囧懘銆忛幓鎰返 upper_price 閸?lower_price"}, ensure_ascii=False)
            
            # 閼惧嘲褰囪ぐ鎾冲娴犻攱鐗?
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
                "message": f"缂冩垶鐗?{bot.name} 瀹告彃鎯庨崝?,
            }, ensure_ascii=False, default=str)
        
        elif action == "stop":
            if grid_id <= 0:
                return json.dumps({"error": "韫囧懘銆忛幓鎰返 grid_id"}, ensure_ascii=False)
            
            bot = await GridStrategy.stop_grid(db=db, grid_id=grid_id, user_id=user_id)
            await db.commit()
            
            return json.dumps({
                "action": "stopped",
                "grid_id": bot.id,
                "message": f"缂冩垶鐗?{bot.name} 瀹告彃浠犲?,
            }, ensure_ascii=False, default=str)
        
        elif action == "delete":
            if grid_id <= 0:
                return json.dumps({"error": "韫囧懘銆忛幓鎰返 grid_id"}, ensure_ascii=False)
            
            from app.models.grid_bot import GridBot, GridStatus
            bot = await db.get(GridBot, grid_id)
            if not bot or bot.user_id != user_id:
                return json.dumps({"error": "缂冩垶鐗告稉宥呯摠閸?}, ensure_ascii=False)
            if bot.status not in (GridStatus.STOPPED, GridStatus.CREATED, GridStatus.COMPLETED):
                return json.dumps({"error": "閸欘亣鍏橀崚鐘绘珟瀹告彃浠犲銏㈡畱缂冩垶鐗?}, ensure_ascii=False)
            
            await db.delete(bot)
            await db.commit()
            return json.dumps({
                "action": "deleted",
                "grid_id": grid_id,
                "message": "缂冩垶鐗稿鎻掑灩闂?,
            }, ensure_ascii=False)
        
        else:
            return json.dumps({
                "error": f"閺堫亞鐓￠幙宥勭稊: {action}",
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
    閺屻儴顕楁禍銈嗘閺冦儴顔?
    
    閸欘垶鈧绻冨?
    - source: agent / autopilot / quant / grid / manual (缁?閸忋劑鍎?
    - result_filter: win / loss (缁?閸忋劑鍎?
    - limit: 鏉╂柨娲栭弶鈩冩殶 (姒涙顓?0)
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


# ==================== 閼奉亜濮╂禍銈嗘缁狅紕鎮婂銉ュ徔 ====================


@register_tool
async def start_autopilot(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
):
    """
    閸氼垰濮╃粵鏍殣閼奉亜濮╂禍銈嗘

    閸欏倹鏆?
        strategy_id: 缁涙牜鏆?ID (閺佹澘鐡?閵嗗倸顩ч弸婊€璐熺粚鍝勫灟閸氼垰濮╅幍鈧張澶嬫た鐠哄啰鐡ラ悾?

    鐠囧瓨妲?
        閸氼垰濮╅崥?autopilot 鐠嬪啫瀹抽崳銊ょ窗閼奉亜濮╅幐澶岀摜閻ｃ儴顔曠€规氨娈戦崨銊︽埂鏉╂劘顢戠拠鍕強:
        閼惧嘲褰囩悰灞惧剰 閳?鐠囧嫪鍙婄粵鏍殣娣団€冲娇 閳?AI 鐎光剝鐗?閳?Pipeline 妞嬪孩甯?閳?閹笛嗩攽
        濮ｅ繑顐奸崨銊︽埂閻ㄥ嫬鍠呯粵鏍箖缁嬪绱扮€瑰本鏆ｇ拋鏉跨秿閸掓澘鍠呯粵鏍ㄦ）韫囨ぞ鑵戦妴?
    """
    from app.services.agent.autopilot import autopilot

    try:
        if strategy_id:
            # 閸氼垰濮╅幐鍥х暰缁涙牜鏆?
            sid = int(strategy_id)
            result = await db.execute(
                select(Strategy).where(
                    Strategy.id == sid,
                    Strategy.user_id == user_id,
                )
            )
            strategy = result.scalar_one_or_none()
            if not strategy:
                return json.dumps({"error": f"缁涙牜鏆?ID {sid} 娑撳秴鐡ㄩ崷?}, ensure_ascii=False)

            strategy.is_active = True
            await db.commit()

            # 婵″倹鐏?autopilot 閺堫亣绻嶇悰宀嬬礉缁斿宓嗛崥顖氬З
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
                "message": f"缁涙牜鏆?'{strategy.name}' 閼奉亜濮╂禍銈嗘瀹告彃鎯庨崝?,
            }, ensure_ascii=False)

        else:
            # 閸氼垰濮╅幍鈧張澶嬫た鐠哄啰鐡ラ悾?
            result = await db.execute(
                select(Strategy).where(
                    Strategy.user_id == user_id,
                    Strategy.is_active == True,
                )
            )
            active = result.scalars().all()
            if not active:
                return json.dumps({"error": "濞屸剝婀佸ú鏄忕┈閻ㄥ嫮鐡ラ悾銉礉鐠囧嘲鍘涢崥顖氬З娑撯偓娑擃亞鐡ラ悾?}, ensure_ascii=False)

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
                "message": f"瀹告彃鎯庨崝?{len(active)} 娑擃亞鐡ラ悾銉ф畱閼奉亜濮╂禍銈嗘",
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
    閸嬫粍顒涢懛顏勫З娴溿倖妲?

    閸欏倹鏆?
        strategy_id: 缁涙牜鏆?ID (閸欘垶鈧?閵嗗倸顩ч弸婊€璐熺粚鍝勫灟閸嬫粍顒涢幍鈧張澶庡殰閸斻劋姘﹂弰?
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
                    "message": f"缁涙牜鏆?'{strategy.name}' 瀹告彃浠犲?,
                }, ensure_ascii=False)
            return json.dumps({"error": f"缁涙牜鏆?ID {sid} 娑撳秴鐡ㄩ崷?}, ensure_ascii=False)
        else:
            await autopilot.stop(user_id)
            # 閺嶅洩顔囬幍鈧張澶岀摜閻ｃ儰璐熼棃鐐存た鐠?
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
                "message": "閹碘偓閺堝鍤滈崝銊ゆ唉閺勬挸鍑￠崑婊勵剾",
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@register_tool
async def get_autopilot_status(
    db: AsyncSession,
    user_id: int,
):
    """
    閺屻儴顕楅懛顏勫З娴溿倖妲楁潻鎰攽閻樿埖鈧?

    鏉╂柨娲?
        鏉╂劘顢戦悩鑸碘偓浣碘偓浣烘磧閹貉傛唉閺勬挸顕妴浣界箥鐞涘本妞傞梹瑁も偓浣告噯閺堢喐顐奸弫鑸偓浣瑰⒔鐞涘本鎼锋担婊勬殶
    """
    from app.services.agent.autopilot import autopilot

    status = autopilot.get_status(user_id)

    # 閼惧嘲褰囧ú鏄忕┈缁涙牜鏆愰崚妤勩€?
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
    閺屻儳婀呴張鈧潻鎴犳畱閼奉亜濮╂禍銈嗘閸愬磭鐡ラ弮銉ョ箶

    閸欏倹鏆?
        symbol: 閸欘垶鈧绱濇潻鍥ㄦ姢娴溿倖妲楃€?
        limit: 鏉╂柨娲栭弶鈩冩殶 (姒涙顓?10)

    鏉╂柨娲?
        濮ｅ繑娼弮銉ョ箶閸栧懎鎯? 閺冨爼妫块妴浣锋唉閺勬挸顕妴浣虹摜閻ｃ儱鎮曢妴浣稿枀缁涙牓鈧竸I閹繆鈧啯鎲崇憰浣碘偓浣规Ц閸氾附澧界悰?
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


# ==================== 鐡掑濞嶉崚鍡樼€藉銉ュ徔 ====================


@register_tool
async def analyze_trend_now(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
):
    """
    閻劍妞跨捄鍐Ъ閸旀寧鏌熷鍫濆瀻閺嬫劕缍嬮崜宥呯閸﹂缚绉奸崝?

    閸欏倹鏆?
        symbol: 娴溿倖妲楃€?(姒涙顓?BTCUSDT)

    鏉╂柨娲?
        鐡掑濞嶉弬鐟版倻閵嗕礁宸辨惔锔衡偓浣瑰皾閸斻劎宸奸妴浣稿З闁插繈鈧礁绔堕崷杞扮秼閸掕翰鈧線鈧倸鎮庨惃鍕摜閻ｃ儳琚崹?
    """
    from app.models.trend_scheme import TrendScheme
    from app.services.quant.trend_analyzer import TrendAnalyzer

    try:
        # 閼惧嘲褰囧ú鏄忕┈閺傝顢?
        result = await db.execute(
            select(TrendScheme).where(
                TrendScheme.user_id == user_id,
                TrendScheme.is_active == True,
            ).limit(1)
        )
        scheme = result.scalar_one_or_none()

        if not scheme:
            return json.dumps({"error": "濞屸剝婀佸ú鏄忕┈閻ㄥ嫯绉奸崝鍨瀻閺嬫劖鏌熷鍫礉鐠囧嘲鍘涢崚娑樼紦閹存牕鍨垫慨瀣妫板嫮鐤嗛弬瑙勵攳"}, ensure_ascii=False)

        # 閼惧嘲褰?K 缁?
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
                return json.dumps({"error": "閼惧嘲褰囩悰灞惧剰婢惰精瑙?}, ensure_ascii=False)

            raw = resp.json()
            klines = [{
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            } for k in raw]

        # 閸掑棙鐎?
        trend_result = analyzer.analyze(config, klines, symbol=symbol.upper())

        # 缂傛挸鐡ㄧ紒鎾寸亯
        from datetime import datetime
        scheme.last_result = trend_result.to_dict()
        scheme.last_run_at = datetime.utcnow()
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
    閼惧嘲褰囬張鈧潻鎴犳畱鐡掑濞嶉崚鍡樼€界紒鎾寸亯 (娑撳秹鍣搁弬鏉垮瀻閺嬫劧绱濈拠璇插絿缂傛挸鐡?

    閸欏倹鏆?
        symbol: 閸欘垶鈧绱濇潻鍥ㄦ姢娴溿倖妲楃€?

    鏉╂柨娲?
        閹碘偓閺堝妞跨捄鍐╂煙濡楀牏娈戦張鈧潻鎴濆瀻閺嬫劗绮ㄩ弸?
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
            return json.dumps({"error": "濞屸剝婀佸ú鏄忕┈閻ㄥ嫯绉奸崝鍨瀻閺嬫劖鏌熷?}, ensure_ascii=False)

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


# ==================== 閺備即妞堝銉ュ徔 ====================


@register_tool
async def get_news(
    db: AsyncSession,
    user_id: int,
    currency: str = "BTC",
    limit: int = 10,
) -> str:
    """
    閺屻儴顕楅張鈧弬鏉垮鐎靛棜鎻ｇ敮浣规煀闂?

    閸欏倹鏆?
        currency: 鐢胶顫掓潻鍥ㄦ姢, 婵?BTC / ETH / SOL (缁?閸忋劑鍎?
        limit: 鏉╂柨娲栭弶鈩冩殶 (姒涙顓?0, 閺堚偓婢?0)

    鏉╂柨娲?
        閺備即妞堥崚妤勩€?(閺嶅洭顣介妴浣疯厬閺傚洦鐖ｆ０妯糕偓浣瑰剰缂侇亗鈧線鍣哥憰浣光偓褋鈧焦娼靛┃鎰┾偓浣规闂?
    """
    from app.services.news.service import get_latest_news

    try:
        articles = await get_latest_news(
            db,
            currency=currency if currency else None,
            limit=min(limit, 50),
        )

        if not articles:
            return json.dumps({"message": f"閺嗗倹妫?{currency} 閻╃鍙ч弬浼存"}, ensure_ascii=False)

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
    閺屻儴顕楃敮鍌氭簚閹懐鍗?(閸╄桨绨弬浼存閹懏鍔呴崚鍡樼€?

    閸欏倹鏆?
        currency: 鐢胶顫? 婵?BTC / ETH (缁?閸忋劑鍎?

    鏉╂柨娲?
        閺佺繝缍嬮幆鍛崕(閻顦?閻鈹?娑擃厽鈧?閵嗕焦鍎忕紒顏勫瀻閺佽埇鈧焦顒滈棃?鐠愮喖娼?娑擃厽鈧勬煀闂傜粯鏆熼柌?
    """
    from app.services.news.service import get_market_sentiment as _get_sentiment

    try:
        sentiment = await _get_sentiment(
            db,
            currency=currency if currency else None,
            hours=24,
        )

        overall = sentiment.get("overall", "neutral")
        overall_zh = {"positive": "閻顦?, "negative": "閻鈹?, "neutral": "娑擃厽鈧?}.get(overall, overall)

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


# ==================== 閺備即妞堥惄鎴炲付鐟欏嫬鍨銉ュ徔 ====================


@register_tool
async def list_alerts(
    db: AsyncSession,
    user_id: int,
) -> str:
    """
    閺屻儳婀呴幍鈧張澶嬫煀闂傝崵娲冮幒褑顫夐崚?

    鏉╂柨娲?
        閻╂垶甯剁憴鍕灟閸掓銆?(閸氬秶袨閵嗕礁鍙ч柨顔跨槤閵嗕浇袝閸欐垶顐奸弫鑸偓浣藉劏閻滃洢鈧焦鈧崵娉╂禍?
    """
    from app.services.news.service import get_user_alerts, _alert_to_dict

    try:
        alerts = await get_user_alerts(db, user_id=user_id)

        if not alerts:
            return json.dumps({"message": "閺嗗倹妫ら惄鎴炲付鐟欏嫬鍨敍灞藉讲娴ｈ法鏁?create_alert 閸掓稑缂?}, ensure_ascii=False)

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
    閸掓稑缂撻弬浼存閻╂垶甯剁憴鍕灟

    閸欏倹鏆?
        name: 鐟欏嫬鍨崥宥囆? 婵?"ETF閸掆晛銈介崑姘樋"
        keywords: 閸忔娊鏁拠宥呭灙鐞? 闁褰块崚鍡涙, 婵?"ETF,BlackRock,闂勫秵浼?
        action: 閸斻劋缍旂猾璇茬€? notify=娴犲懘鈧氨鐓? trade=閼奉亜濮╂禍銈嗘
        trade_symbol: 娴溿倖妲楃€?(action=trade閺冨墎鏁撻弫?
        trade_side: 娴溿倖妲楅弬鐟版倻, buy/sell/auto (auto=閺嶈宓侀弬浼存閹懏鍔呴懛顏勫З閸掋倖鏌?
        trade_position_pct: 娴犳挷缍呭В鏂剧伐% (1-15)
        trade_leverage: 閺夌姵娼岄崐宥嗘殶 (1-20)
        trade_stop_loss_pct: 濮濄垺宕惂鎯у瀻濮?
        trade_take_profit_pct: 濮濄垻娉╅惂鎯у瀻濮?
        news_categories: 閸欘垶鈧? 閸掑棛琚潻鍥ㄦ姢, 闁褰块崚鍡涙 (macro/etf/regulation/exchange/whale/project)
        currencies: 閸欘垶鈧? 鐢胶顫掓潻鍥ㄦ姢, 闁褰块崚鍡涙 (BTC/ETH/SOL)
        sentiment_filter: 閹懏鍔呮潻鍥ㄦ姢, any/positive/negative

    鏉╂柨娲?
        閸掓稑缂撻幋鎰閻ㄥ嫯顫夐崚娆掝嚊閹?
    """
    from app.models.news import NewsAlert
    from app.services.news.service import get_user_alerts, _alert_to_dict

    try:
        if not name:
            return json.dumps({"error": "鐠囬攱褰佹笟娑滎潐閸掓瑥鎮曠粔?(name)"}, ensure_ascii=False)
        if not keywords:
            return json.dumps({"error": "鐠囬攱褰佹笟娑樺彠闁款喛鐦?(keywords), 闁褰块崚鍡涙"}, ensure_ascii=False)

        # 濡偓閺屻儴顫夐崚娆愭殶闁插繘妾洪崚?
        existing = await get_user_alerts(db, user_id=user_id)
        if len(existing) >= 20:
            return json.dumps({"error": "閻╂垶甯剁憴鍕灟瀹歌尪鎻稉濠囨 (20閺?"}, ensure_ascii=False)

        # 鐟欙絾鐎介柅妤€褰块崚鍡涙閻ㄥ嫬鍨悰?
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        cat_list = [c.strip() for c in news_categories.split(",") if c.strip()] if news_categories else None
        cur_list = [c.strip().upper() for c in currencies.split(",") if c.strip()] if currencies else None

        # 妤犲矁鐦?trade 濡€崇础閸欏倹鏆?
        if action == "trade" and not trade_symbol:
            return json.dumps({"error": "娴溿倖妲楀Ο鈥崇础闂団偓鐟曚焦瀵氱€?trade_symbol"}, ensure_ascii=False)

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
            "message": f"閻╂垶甯剁憴鍕灟 '{name}' 閸掓稑缂撻幋鎰",
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
    娣囶喗鏁?閸氼垰浠?閸掔娀娅庨弬浼存閻╂垶甯剁憴鍕灟

    閸欏倹鏆?
        alert_id: 鐟欏嫬鍨?ID (韫囧懎锝?
        action: 閹垮秳缍旂猾璇茬€?
            - update: 娣囶喗鏁肩憴鍕灟 (姒涙顓?
            - activate: 閸氼垳鏁ょ憴鍕灟
            - deactivate: 閺嗗倸浠犵憴鍕灟
            - delete: 閸掔娀娅庣憴鍕灟
        name: 閺傛澘鎮曠粔?(缁?娑撳秳鎱ㄩ弨?
        keywords: 閺傛澘鍙ч柨顔跨槤, 闁褰块崚鍡涙 (缁?娑撳秳鎱ㄩ弨?
        is_active: "true"/"false" (缁?娑撳秳鎱ㄩ弨?
        trade_side: buy/sell/auto (缁?娑撳秳鎱ㄩ弨?
        trade_symbol: 娴溿倖妲楃€?(缁?娑撳秳鎱ㄩ弨?
        trade_position_pct: 娴犳挷缍呭В鏂剧伐% (0=娑撳秳鎱ㄩ弨?
        trade_leverage: 閺夌姵娼岄崐宥嗘殶 (0=娑撳秳鎱ㄩ弨?
        trade_stop_loss_pct: 濮濄垺宕? (0=娑撳秳鎱ㄩ弨?
        trade_take_profit_pct: 濮濄垻娉? (0=娑撳秳鎱ㄩ弨?

    鏉╂柨娲?
        閺囧瓨鏌婇崥搴ｆ畱鐟欏嫬鍨拠锔藉剰
    """
    from sqlalchemy import select as sa_select
    from app.models.news import NewsAlert
    from app.services.news.service import _alert_to_dict

    try:
        if alert_id <= 0:
            return json.dumps({"error": "鐠囬攱褰佹笟娑滎潐閸?ID (alert_id)"}, ensure_ascii=False)

        result = await db.execute(
            sa_select(NewsAlert).where(
                NewsAlert.id == alert_id,
                NewsAlert.user_id == user_id,
            )
        )
        alert = result.scalar_one_or_none()
        if not alert:
            return json.dumps({"error": f"鐟欏嫬鍨?#{alert_id} 娑撳秴鐡ㄩ崷?}, ensure_ascii=False)

        # 閸掔娀娅庨幙宥勭稊
        if action == "delete":
            alert_name = alert.name
            await db.delete(alert)
            await db.commit()
            return json.dumps({"message": f"鐟欏嫬鍨?'{alert_name}' 瀹告彃鍨归梽?}, ensure_ascii=False)

        # 韫囶偅宓庨崥顖氫粻
        if action == "activate":
            alert.is_active = True
            await db.commit()
            return json.dumps({"message": f"鐟欏嫬鍨?'{alert.name}' 瀹告彃鎯庨悽?}, ensure_ascii=False)
        if action == "deactivate":
            alert.is_active = False
            await db.commit()
            return json.dumps({"message": f"鐟欏嫬鍨?'{alert.name}' 瀹稿弶娈忛崑?}, ensure_ascii=False)

        # 闁劕鐡у▓鍨纯閺?
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
            "message": f"鐟欏嫬鍨?'{alert.name}' 瀹稿弶娲块弬?,
            "alert": _alert_to_dict(alert),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ==================== 閺備即妞?鐢倸婧€閸忓疇浠堥崚鍡樼€藉銉ュ徔 ====================


@register_tool
async def analyze_news_impact(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    days: int = 30,
    window_hours: str = "1,4,24",
) -> str:
    """
    閸掑棙鐎介弬浼存鐎电懓绔堕崷铏规畱瑜板崬鎼?閳?閸欐垹骞囬弬浼存-娴犻攱鐗搁崗瀹犱粓鐟欏嫬绶?

    鐎电绻冮崢绫掓径鈺冩畱閺備即妞堥敍宀冾吀缁犳鏌婇梻璇插絺鐢啫鎮楅惃鍕幆閺嶇厧褰夐崠鏍电礉閹稿鍨庣猾?閹懏鍔呴崚鍡欑矋缂佺喕顓搁敍?
    閹垫儳鍤?閸濐亞琚弬浼存閸欐垹鏁撻崥搴＄閸﹀搫顩ф担鏇炲冀鎼?閻ㄥ嫯顫夊瀣ㄢ偓?

    閸欏倹鏆?
        symbol: 娴溿倖妲楃€?(姒涙顓?BTCUSDT)
        days: 閸ョ偟婀呮径鈺傛殶 (姒涙顓?0, 閺堚偓婢?0)
        window_hours: 鐟欏倸鐧傜粣妤€褰? 闁褰块崚鍡涙 (姒涙顓?"1,4,24" 鐞涖劎銇?h/4h/24h閸氬海娈戝☉銊ㄧ┘)

    鏉╂柨娲?
        閸氬嫬鍨庣猾?閹懏鍔呯紒鍕値娑撳娈戦獮鍐叉綆濞戙劏绌奸獮鍛偓浣藉劏閻滃洢鈧焦鐗遍張顒佹殶, 娴犮儱寮烽崣鎴犲箛閻ㄥ嫯顫夊瀣偓鑽ょ波
    """
    from sqlalchemy import select as sa_select, and_
    from app.models.news import NewsArticle
    from app.models.market import Kline
    from datetime import datetime, timedelta

    try:
        days = min(days, 90)
        windows = [int(h.strip()) for h in window_hours.split(",") if h.strip()]
        if not windows:
            windows = [1, 4, 24]

        cutoff = datetime.utcnow() - timedelta(days=days)

        # 1. 閺屻儴顕楅張?currency 閺嶅洨顒烽惃鍕煀闂?
        news_result = await db.execute(
            sa_select(NewsArticle).where(
                NewsArticle.published_at >= cutoff,
            ).order_by(NewsArticle.published_at.desc()).limit(500)
        )
        articles = news_result.scalars().all()

        if not articles:
            return json.dumps({
                "message": f"鏉╁洤骞?{days} 婢垛晜鐥呴張澶嬫煀闂傜粯鏆熼幑顕嗙礉閺冪姵纭堕崚鍡樼€?,
            }, ensure_ascii=False)

        # 2. 鐎佃鐦￠弶鈩冩煀闂備紮绱濋懢宄板絿閸欐垵绔烽弮?+ 閸氬嫮鐛ラ崣锝呮倵閻ㄥ嫪鐜弽?
        base_symbol = symbol.upper()
        impact_records = []

        for article in articles:
            pub_ts = int(article.published_at.timestamp() * 1000)

            # 閼惧嘲褰囬弬浼存閸欐垵绔烽弮鍓佹畱1h K缁?(娴ｆ粈璐熼崺鍝勫櫙娴?
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

            # 閸氬嫮鐛ラ崣锝呮倵閻ㄥ嫪鐜弽鐓庡綁閸?
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
                "message": f"閺?{len(articles)} 閺夆剝鏌婇梻璁崇稻閺冪姵纭堕崠褰掑帳閸?{base_symbol} K缁炬寧鏆熼幑?,
            }, ensure_ascii=False)

        # 3. 閹?(category, sentiment) 閸掑棛绮嶇紒鐔活吀
        from collections import defaultdict
        groups = defaultdict(list)
        for rec in impact_records:
            key = f"{rec['category']}|{rec['sentiment']}"
            groups[key].append(rec)

        # 4. 鐠侊紕鐣荤紒鐔活吀閹稿洦鐖?
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

        # 閹?4h 楠炲啿娼庡☉銊ョ畽閹烘帒绨?
        sort_key = "4h_avg_change" if "4h" in windows else f"{windows[0]}h_avg_change"
        group_stats.sort(key=lambda x: abs(x.get(sort_key, 0)), reverse=True)

        # 5. 閸欐垹骞囩憴鍕伐 (閺勬崘鎲插Ο鈥崇础)
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
                        "rule": f"{s['category']}缁?+ {s['sentiment']}閹懏鍔?閳?{w}h閸氬骸閽╅崸鍥ㄥ畾{avg:.2f}%",
                        "direction": "閸嬫艾顦?,
                        "avg_change": avg,
                        "win_rate": wr,
                        "confidence": "妤? if (samples >= 5 and wr >= 70) else "娑?,
                        "category": s["category"],
                        "sentiment": s["sentiment"],
                        "window": w,
                        "samples": samples,
                    })
                elif avg < -0.5 and wr <= 40:
                    real_wr = 100 - wr  # 閸嬫氨鈹栭懗婊呭芳
                    patterns.append({
                        "rule": f"{s['category']}缁?+ {s['sentiment']}閹懏鍔?閳?{w}h閸氬骸閽╅崸鍥┘{abs(avg):.2f}%",
                        "direction": "閸嬫氨鈹?,
                        "avg_change": avg,
                        "win_rate": real_wr,
                        "confidence": "妤? if (samples >= 5 and real_wr >= 70) else "娑?,
                        "category": s["category"],
                        "sentiment": s["sentiment"],
                        "window": w,
                        "samples": samples,
                    })

        patterns.sort(key=lambda x: abs(x["avg_change"]), reverse=True)

        return json.dumps({
            "symbol": base_symbol,
            "analysis_period": f"鏉╁洤骞搟days}婢?,
            "total_news": len(articles),
            "matched_news": len(impact_records),
            "windows": [f"{w}h" for w in windows],
            "group_stats": group_stats[:15],
            "discovered_patterns": patterns[:10],
            "hint": "娴ｈ法鏁?auto_generate_alerts 閸欘垰鐨㈤崣鎴犲箛閻ㄥ嫯顫夊瀣殰閸斻劌鍨卞杞拌礋閻╂垶甯剁憴鍕灟",
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
    閺嶈宓侀崢鍡楀蕉閺備即妞?鐢倸婧€閸忓疇浠堥崚鍡樼€? 閼奉亜濮╅悽鐔稿灇閻╂垶甯剁憴鍕灟

    閸忓牐绻嶇悰?analyze_news_impact 閸欐垹骞囩憴鍕伐, 閻掕泛鎮楃€电鍎ㄩ悳鍥Т鏉╁洭妲囬崐鑲╂畱濡€崇础閼奉亜濮╅崚娑樼紦 Alert閵?

    閸欏倹鏆?
        symbol: 娴溿倖妲楃€?(姒涙顓?BTCUSDT)
        days: 閸掑棙鐎介崶鐐垫箙婢垛晜鏆?(姒涙顓?0)
        min_win_rate: 閺堚偓娴ｅ氦鍎ㄩ悳鍥閸? (姒涙顓?0, 娴ｅ簼绨銈呪偓闂寸瑝閸掓稑缂?
        min_samples: 閺堚偓鐏忔垶鐗遍張顒佹殶 (姒涙顓?)
        action: 鐟欏嫬鍨崝銊ょ稊, notify=娴犲懘鈧氨鐓? trade=閼奉亜濮╂禍銈嗘
        trade_position_pct: 娴犳挷缍? (action=trade閺?
        trade_leverage: 閺夌姵娼?(action=trade閺?
        trade_stop_loss_pct: 濮濄垺宕? (action=trade閺?
        trade_take_profit_pct: 濮濄垻娉? (action=trade閺?

    鏉╂柨娲?
        閼奉亜濮╅崚娑樼紦閻ㄥ嫯顫夐崚娆忓灙鐞?
    """
    from app.models.news import NewsAlert
    from app.services.news.service import get_user_alerts

    try:
        # 1. 閸忓牐绻嶇悰灞藉瀻閺?
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
                "message": f"鏉╁洤骞搟days}婢垛晜婀崣鎴犲箛閺勬崘鎲查惃鍕煀闂?鐢倸婧€閸忓疇浠堢憴鍕伐 (闂団偓鐟曚焦娲挎径姘殶閹?",
                "total_news_analyzed": analysis.get("total_news", 0),
            }, ensure_ascii=False)

        # 2. 濡偓閺屻儱鍑￠張澶庮潐閸掓瑦鏆熼柌?
        existing = await get_user_alerts(db, user_id=user_id)
        remaining_slots = 20 - len(existing)
        if remaining_slots <= 0:
            return json.dumps({"error": "閻╂垶甯剁憴鍕灟瀹歌尪鎻稉濠囨(20閺?, 鐠囧嘲鍘涢崚鐘绘珟閺冄嗩潐閸?}, ensure_ascii=False)

        # 3. 閹稿顫夐崚娆戞晸閹?Alert
        # 閸掑棛琚崚鏉垮彠闁款喛鐦濋惃鍕Ё鐏?
        category_keywords = {
            "macro": ["fed", "rate cut", "rate hike", "inflation", "CPI", "GDP", "FOMC", "閼辨柨鍋?, "闂勫秵浼?, "閸旂姵浼?],
            "etf": ["ETF", "BlackRock", "Grayscale", "Fidelity", "inflow", "outflow", "spot ETF"],
            "regulation": ["SEC", "regulation", "lawsuit", "compliance", "ban", "license", "閻╂垹顓?],
            "exchange": ["Binance", "Coinbase", "listing", "delist", "exchange", "娑撳﹤绔?],
            "whale": ["whale", "transfer", "wallet", "dormant", "accumulation", "瀹搞劑鍝?],
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

            # 閻㈢喐鍨氱憴鍕灟閸?
            cat_zh = {
                "macro": "鐎瑰繗顫?, "etf": "ETF", "regulation": "閻╂垹顓?,
                "exchange": "娴溿倖妲楅幍鈧?, "whale": "瀹搞劑鍝?, "project": "妞ゅ湱娲?,
            }.get(category, category)
            sent_zh = {"positive": "閸掆晛銈?, "negative": "閸掆晝鈹?, "neutral": "娑擃厽鈧?}.get(sentiment, sentiment)

            name = f"[AI閸欐垹骞嘳 {cat_zh}{sent_zh}閳姾direction} ({win_rate:.0f}%閼虫粎宸?"

            # 濡偓閺屻儲妲搁崥锕€鍑＄€涙ê婀崥灞芥倳鐟欏嫬鍨?
            if any(e.get("name") == name for e in existing):
                continue

            # 閼惧嘲褰囬崗鎶芥暛鐠?
            keywords = category_keywords.get(category, [category])

            # 閺嶈宓侀弬鐟版倻鐠佸墽鐤嗘禍銈嗘閺傜懓鎮?
            trade_side = "buy" if direction == "閸嬫艾顦? else "sell"
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
            "message": f"閸╄桨绨潻鍥у箵{days}婢垛晛鍨庨弸? 閼奉亜濮╅崚娑樼紦娴?{len(created_alerts)} 閺夛紕娲冮幒褑顫夐崚?,
            "analysis_summary": {
                "total_news": analysis.get("total_news", 0),
                "matched_news": analysis.get("matched_news", 0),
                "patterns_found": len(patterns),
                "rules_created": len(created_alerts),
            },
            "created_alerts": created_alerts,
            "skipped_reason": f"鐠哄疇绻冮懗婊呭芳<{min_win_rate}%閹存牗鐗遍張?{min_samples}閻ㄥ嫭膩瀵? if len(patterns) > len(created_alerts) else None,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
