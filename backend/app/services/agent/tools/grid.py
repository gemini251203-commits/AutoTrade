"""
网格交易工具 — manage_grid
"""

import json
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from ._registry import register_tool


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
    leverage: int = 15,
    grid_id: int = 0,
) -> str:
    """
    管理网格交易
    
    action 可选:
    - list: 查看所有网格机器人
    - start: 创建并启动网格 (需要 symbol/upper_price/lower_price/grid_count/investment)
    - stop: 停止网格 (需要 grid_id)
    - delete: 删除网格 (需要 grid_id)
    - cleanup: 批量清理所有废弃网格 (已停止/已完成/已创建未启动)
    """
    from app.services.grid import GridStrategy
    
    try:
        action = action.lower().strip()
        
        if action == "list":
            bots = await GridStrategy.get_user_grid_bots(db, user_id)
            bot_list = []
            abandoned_count = 0
            for b in bots:
                status_val = b.status.value if hasattr(b.status, 'value') else str(b.status)
                if status_val in ('STOPPED', 'COMPLETED', 'CREATED'):
                    abandoned_count += 1
                bot_list.append({
                    "id": b.id,
                    "name": b.name,
                    "symbol": b.symbol,
                    "status": status_val,
                    "upper_price": str(b.upper_price),
                    "lower_price": str(b.lower_price),
                    "grid_count": b.grid_count,
                    "investment": str(b.investment),
                    "total_profit": str(b.total_profit),
                    "filled_buy_count": b.filled_buy_count,
                    "filled_sell_count": b.filled_sell_count,
                })
            result = {
                "action": "list",
                "count": len(bot_list),
                "bots": bot_list,
            }
            if abandoned_count > 0:
                result["warning"] = f"⚠️ 有 {abandoned_count} 个废弃网格待清理，请调用 manage_grid(action=cleanup) 清理"
            return json.dumps(result, ensure_ascii=False, default=str)
        
        elif action == "start":
            if upper_price <= 0 or lower_price <= 0:
                return json.dumps({"error": "必须提供 upper_price 和 lower_price"}, ensure_ascii=False, default=str)
            
            # 获取当前价格
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            ticker = await client.get_ticker(symbol.upper())
            current_price = Decimal(str(ticker.get("lastPrice", 0))) if ticker else Decimal("0")
            
            # 1. 先创建网格机器人
            bot = await GridStrategy.create_grid_bot(
                db=db,
                user_id=user_id,
                name=f"Grid {symbol.upper()} {grid_count}格",
                symbol=symbol.upper(),
                upper_price=Decimal(str(upper_price)),
                lower_price=Decimal(str(lower_price)),
                grid_count=grid_count,
                investment=Decimal(str(investment)),
                leverage=leverage,
            )
            await db.flush()
            
            # 2. 再启动网格
            bot = await GridStrategy.start_grid(
                db=db,
                bot_id=bot.id,
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
                "quantity_per_grid": str(bot.quantity_per_grid),
                "message": f"网格 {bot.name} 已启动",
            }, ensure_ascii=False, default=str)
        
        elif action == "stop":
            if grid_id <= 0:
                return json.dumps({"error": "必须提供 grid_id"}, ensure_ascii=False, default=str)
            
            bot = await GridStrategy.stop_grid(db=db, bot_id=grid_id)
            await db.commit()
            
            return json.dumps({
                "action": "stopped",
                "grid_id": bot.id,
                "message": f"网格 {bot.name} 已停止",
            }, ensure_ascii=False, default=str)
        
        elif action == "delete":
            if grid_id <= 0:
                return json.dumps({"error": "必须提供 grid_id"}, ensure_ascii=False, default=str)
            
            from app.models.grid_bot import GridBot, GridStatus
            bot = await db.get(GridBot, grid_id)
            if not bot or bot.user_id != user_id:
                return json.dumps({"error": "网格不存在"}, ensure_ascii=False, default=str)
            if bot.status not in (GridStatus.STOPPED, GridStatus.CREATED, GridStatus.COMPLETED):
                return json.dumps({"error": "只能删除已停止的网格"}, ensure_ascii=False, default=str)
            
            await db.delete(bot)
            await db.commit()
            return json.dumps({
                "action": "deleted",
                "grid_id": grid_id,
                "message": "网格已删除",
            }, ensure_ascii=False, default=str)
        
        elif action == "cleanup":
            from app.models.grid_bot import GridBot, GridStatus
            from app.models.position import Position, PositionStatus
            from sqlalchemy import select, update
            
            result = await db.execute(
                select(GridBot).where(
                    GridBot.user_id == user_id,
                    GridBot.status.in_([GridStatus.STOPPED, GridStatus.CREATED, GridStatus.COMPLETED]),
                )
            )
            abandoned = result.scalars().all()
            deleted_ids = []
            for bot in abandoned:
                deleted_ids.append(bot.id)
                await db.delete(bot)
            
            # 🔥 清理孤儿仓位: 如果没有 RUNNING 的网格 bot，把 grid 仓位改为 manual
            running_result = await db.execute(
                select(GridBot.id).where(
                    GridBot.user_id == user_id,
                    GridBot.status == GridStatus.RUNNING,
                )
            )
            running_ids = running_result.scalars().all()
            
            orphan_count = 0
            if not running_ids:
                # 没有运行中的网格 → 所有 grid 仓位都是孤儿
                orphan_result = await db.execute(
                    update(Position)
                    .where(
                        Position.user_id == user_id,
                        Position.source == "grid",
                        Position.status == PositionStatus.OPEN,
                    )
                    .values(source="manual")
                    .returning(Position.id)
                )
                orphan_count = len(orphan_result.fetchall())
            
            if deleted_ids or orphan_count:
                await db.commit()
            return json.dumps({
                "action": "cleanup",
                "deleted_count": len(deleted_ids),
                "deleted_ids": deleted_ids,
                "orphan_positions_fixed": orphan_count,
                "message": f"已清理 {len(deleted_ids)} 个废弃网格" + (f"，修正 {orphan_count} 个孤儿仓位" if orphan_count else "") if (deleted_ids or orphan_count) else "没有废弃网格需要清理",
            }, ensure_ascii=False, default=str)
        
        else:
            return json.dumps({
                "error": f"未知操作: {action}",
                "valid_actions": ["list", "start", "stop", "delete", "cleanup"],
            }, ensure_ascii=False, default=str)
    
    except Exception as e:
        logger.error(f"[AgentTools] manage_grid failed: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)
