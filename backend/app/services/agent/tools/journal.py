"""
交易日志工具 — get_trade_journal, get_trading_logs
"""

import json
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from ._registry import register_tool


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
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)



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
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)
