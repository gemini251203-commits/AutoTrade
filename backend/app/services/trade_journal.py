"""
Trade Journal Service
======================
统一交易记忆生成器

在仓位平仓时自动生成结构化的交易记忆 (TradeMemory)。
所有来源的交易 (手动/AI Agent/信号助手/量化策略) 统一记录。

挂载点: PositionManager.close_position()
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position
from app.models.strategy import TradeMemory
from app.core.time_utils import utc_now


class TradeJournal:
    """统一交易记忆生成器"""

    @staticmethod
    async def record_close(
        db: AsyncSession,
        position: Position,
        pnl: Decimal,
        close_price: Decimal,
        close_reason: str = "manual",
    ) -> Optional[TradeMemory]:
        """
        平仓时自动生成交易记忆
        
        Args:
            db: 数据库会话
            position: 已平仓的仓位
            pnl: 已实现盈亏
            close_price: 平仓价格
            close_reason: 平仓原因 (manual/tp_hit/sl_hit/liquidated/signal/strategy)
        
        Returns:
            创建的 TradeMemory 实例
        """
        try:
            # 计算 ROE%
            margin = float(position.margin) if position.margin else 0
            pnl_float = float(pnl)
            pnl_pct = (pnl_float / margin * 100) if margin > 0 else 0
            
            # 判断 win/loss
            if pnl_float > 0.01:
                trade_result = "win"
            elif pnl_float < -0.01:
                trade_result = "loss"
            else:
                trade_result = "breakeven"
            
            # 计算持仓时长
            duration_minutes = None
            if position.created_at:
                close_time = position.closed_at or utc_now()
                delta = close_time - position.created_at
                duration_minutes = int(delta.total_seconds() / 60)
            
            # 交易来源
            source = getattr(position, "source", "manual") or "manual"
            open_reason = getattr(position, "open_reason", None)
            commission = float(position.total_commission) if getattr(position, "total_commission", None) else 0
            
            # 风控记录
            had_sl = position.stop_loss is not None
            had_tp = position.take_profit is not None
            
            # 🔥 Layer 3: 零价格防护 — 绝不写入 exit_price=0 的污染账单
            exit_price_val = float(close_price)
            entry_price_val = float(position.entry_price)
            
            if exit_price_val <= 0:
                logger.error(
                    f"[TradeJournal] BLOCKED: exit_price={exit_price_val} for "
                    f"{position.symbol} position #{position.id}. Refusing to create ghost record."
                )
                return None
            
            if entry_price_val <= 0:
                logger.error(
                    f"[TradeJournal] BLOCKED: entry_price={entry_price_val} for "
                    f"{position.symbol} position #{position.id}. Data corrupted."
                )
                return None
            
            # 异常盈亏检测: |ROE%| > 1000% 告警 (可能数据错误)
            roe_check = abs(pnl_float / margin * 100) if margin > 0 else 0
            if roe_check > 1000:
                logger.warning(
                    f"[TradeJournal] ⚠️ SUSPICIOUS: {position.symbol} ROE={roe_check:.0f}% "
                    f"entry={entry_price_val} exit={exit_price_val} pnl={pnl_float}"
                )
            
            memory = TradeMemory(
                user_id=position.user_id,
                symbol=position.symbol,
                source=source,
                position_id=position.id,
                side=position.side.value if position.side else None,
                entry_price=entry_price_val,
                exit_price=exit_price_val,
                leverage=position.leverage,
                margin_used=margin,
                trade_result=trade_result,
                pnl_pct=round(pnl_pct, 2),
                pnl_usdt=round(pnl_float, 4),
                duration_minutes=duration_minutes,
                close_reason=close_reason,
                commission=commission,
                had_stop_loss=had_sl,
                had_take_profit=had_tp,
                open_reason=open_reason,
            )
            
            db.add(memory)
            
            emoji = "✅" if trade_result == "win" else "❌"
            logger.info(
                f"[TradeJournal] {emoji} [{source}] {position.symbol} "
                f"{position.side.value} {pnl_float:+.2f} USDT ({pnl_pct:+.1f}%) "
                f"duration={duration_minutes}min close={close_reason}"
            )
            
            return memory
            
        except Exception as e:
            logger.error(f"[TradeJournal] 记录交易记忆失败: {e}")
            return None
