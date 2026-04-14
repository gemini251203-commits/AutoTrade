"""
交易工具 — place_order, close_position, change_leverage, cancel_order
"""

import json
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.order import OrderSide, OrderType
from app.models.position import Position, PositionSide, PositionStatus
from app.models.wallet import Wallet
from app.models.security import security_manager
from ._registry import register_tool, agent_source_var, agent_name_var


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
                }, ensure_ascii=False, default=str)


        # ==================== 通过预检验, 执行下单 ====================
        order_side = OrderSide(side.lower())
        otype = OrderType(order_type.lower())
        order_price = Decimal(str(price)) if price and float(price) > 0 else None

        # 止损止盈参数
        sl = Decimal(str(stop_loss)) if stop_loss and float(stop_loss) > 0 else None
        tp = Decimal(str(take_profit)) if take_profit and float(take_profit) > 0 else None
        
        # 🔥 Hub/Autopilot 来源: 如果 AI 没传 TP/SL，自动从风控配置读取默认值
        source_label = agent_source_var.get('agent')
        if source_label in ('hub', 'autopilot') and current_price > 0 and (not sl or not tp):
            from app.core.risk_config import risk_config
            cfg = risk_config.load_for_user(user_id)
            sl_pct = Decimal(str(cfg.get("default_sl_pct", 2.0))) / 100
            tp_pct = Decimal(str(cfg.get("default_tp_pct", 4.0))) / 100
            cp = Decimal(str(current_price))
            if side.lower() == 'buy':
                if not sl:
                    sl = (cp * (1 - sl_pct)).quantize(Decimal("0.01"))
                    logger.info(f"[AgentTools] Auto SL for BUY: {sl} ({cfg.get('default_sl_pct')}%)")
                if not tp:
                    tp = (cp * (1 + tp_pct)).quantize(Decimal("0.01"))
                    logger.info(f"[AgentTools] Auto TP for BUY: {tp} ({cfg.get('default_tp_pct')}%)")
            else:
                if not sl:
                    sl = (cp * (1 + sl_pct)).quantize(Decimal("0.01"))
                    logger.info(f"[AgentTools] Auto SL for SELL: {sl} ({cfg.get('default_sl_pct')}%)")
                if not tp:
                    tp = (cp * (1 - tp_pct)).quantize(Decimal("0.01"))
                    logger.info(f"[AgentTools] Auto TP for SELL: {tp} ({cfg.get('default_tp_pct')}%)")

        # 根据来源上下文确定 source 和 agent 名称
        source_label = agent_source_var.get('agent')
        current_agent_name = agent_name_var.get('')
        
        # note 格式: [Hub:deepseek] 下单 或 [Agent] 下单
        if current_agent_name:
            note_prefix = f"[{source_label.title()}:{current_agent_name}]"
        else:
            note_prefix = f"[{source_label.title()}]"

        # ==================== 直接通过 OrderExecutor 下单 (绕过 Pipeline) ====================
        # Pipeline 只供量化策略使用，AI Hub / 手动下单直接走 OrderExecutor
        from app.services.trading import OrderExecutor
        
        # 基础风控: 最大杠杆限制
        from app.core.risk_config import risk_config as _rc
        rc = _rc.load_for_user(user_id)
        max_lev = rc.get("max_leverage", 20)
        if int(leverage) > max_lev:
            return json.dumps({
                "success": False,
                "error": f"杠杆 {leverage}x 超过风控上限 {max_lev}x",
            }, ensure_ascii=False, default=str)
        
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
            note=f"{note_prefix} 下单",
        )
        
        result = {
            "success": True,
            "order_id": order.id,
            "symbol": symbol,
            "side": side,
            "quantity": str(order.quantity),
            "leverage": order.leverage,
            "status": order.status.value,
            "stop_loss": str(sl) if sl else None,
            "take_profit": str(tp) if tp else None,
            "message": "订单已执行",
        }
        
        return json.dumps(result, ensure_ascii=False, default=str)

    except OrderError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[AgentTools] place_order failed: {e}")
        return json.dumps({"success": False, "error": f"下单失败: {str(e)}"}, ensure_ascii=False, default=str)


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
        # 🔥 Layer 1: 零价格防护 — 自动获取当前市场价
        if not close_price or close_price <= 0:
            # 先查询仓位获取 symbol
            from sqlalchemy import select
            from app.models.position import Position
            result = await db.execute(
                select(Position).where(Position.id == int(position_id))
            )
            pos = result.scalar_one_or_none()
            if pos:
                try:
                    from app.services.market_collector import market_collector
                    price_data = market_collector.get_price(pos.symbol)
                    if price_data and price_data.get("price"):
                        close_price = float(price_data["price"])
                        logger.warning(
                            f"[AgentTools] close_position: close_price was 0, "
                            f"auto-fetched market price {close_price} for {pos.symbol}"
                        )
                except Exception as price_err:
                    logger.warning(f"[AgentTools] Failed to auto-fetch price: {price_err}")
            
            # 二次检查：如果仍然为 0，拒绝执行
            if not close_price or close_price <= 0:
                return json.dumps({
                    "success": False,
                    "error": "平仓价格不能为 0！请提供有效的 close_price 参数。",
                }, ensure_ascii=False)

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
        }, ensure_ascii=False, default=str)

    except PositionError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[AgentTools] close_position failed: {e}")
        return json.dumps({"success": False, "error": f"平仓失败: {str(e)}"}, ensure_ascii=False, default=str)


@register_tool
async def change_leverage(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    leverage: int = 10,
) -> str:
    """修改持仓杠杆倍数（支持持仓中调整，1-125倍）"""
    try:
        symbol = symbol.upper()
        leverage = int(leverage)
        
        if leverage < 1 or leverage > 125:
            return json.dumps({
                "success": False,
                "error": f"杠杆必须在 1-125 之间，当前输入: {leverage}",
            }, ensure_ascii=False, default=str)
        
        # 查找该交易对的持仓
        result = await db.execute(
            select(Position).where(
                Position.user_id == user_id,
                Position.symbol == symbol,
                Position.status == PositionStatus.OPEN,
            )
        )
        position = result.scalar_one_or_none()
        
        if not position:
            return json.dumps({
                "success": False,
                "error": f"未找到 {symbol} 的持仓，无法修改杠杆",
            }, ensure_ascii=False, default=str)
        
        old_leverage = position.leverage
        if old_leverage == leverage:
            return json.dumps({
                "success": True,
                "message": f"{symbol} 杠杆已经是 {leverage}x，无需修改",
            }, ensure_ascii=False, default=str)
        
        # 计算新旧保证金差额
        old_margin = position.margin
        new_margin = (position.size * position.entry_price) / Decimal(str(leverage))
        margin_diff = new_margin - old_margin  # 正=需要追加, 负=可释放
        
        # 调整钱包余额
        from app.services.wallet import WalletManager
        wallet = await WalletManager.get_wallet(db, user_id, for_update=True)
        
        if margin_diff > 0:
            # 提高保证金（降低杠杆）：从余额中扣除
            if wallet.balance < margin_diff:
                return json.dumps({
                    "success": False,
                    "error": (
                        f"余额不足以降低杠杆: 需要追加 {float(margin_diff):.2f} USDT 保证金，"
                        f"可用余额 {float(wallet.balance):.2f} USDT"
                    ),
                }, ensure_ascii=False, default=str)
            wallet.balance -= margin_diff
        else:
            # 释放保证金（提高杠杆）：返还到余额
            wallet.balance += abs(margin_diff)
        
        # 更新仓位
        position.leverage = leverage
        position.margin = new_margin
        
        logger.info(
            f"[AgentTools] Leverage changed: {symbol} {old_leverage}x → {leverage}x, "
            f"margin {float(old_margin):.2f} → {float(new_margin):.2f}, "
            f"diff={float(margin_diff):+.2f}"
        )
        
        return json.dumps({
            "success": True,
            "symbol": symbol,
            "position_id": position.id,
            "old_leverage": old_leverage,
            "new_leverage": leverage,
            "old_margin": round(float(old_margin), 2),
            "new_margin": round(float(new_margin), 2),
            "margin_change": round(float(margin_diff), 2),
            "message": (
                f"{symbol} 杠杆已从 {old_leverage}x 调整为 {leverage}x，"
                f"保证金 {float(old_margin):.2f} → {float(new_margin):.2f} USDT"
            ),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"[AgentTools] change_leverage failed: {e}")
        return json.dumps({"success": False, "error": f"修改杠杆失败: {str(e)}"}, ensure_ascii=False, default=str)


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
        }, ensure_ascii=False, default=str)

    except OrderError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[AgentTools] cancel_order failed: {e}")
        return json.dumps({"success": False, "error": f"取消失败: {str(e)}"}, ensure_ascii=False, default=str)
