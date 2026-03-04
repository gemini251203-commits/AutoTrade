"""
Reset Service
==============
账户重置服务 — 从 wallet API 中抽取的业务逻辑

原来的 /reset 是一个 170 行的 God Function，
现在拆分为独立的 ResetService 以提高可测试性和模块化。
"""

import os
from decimal import Decimal

from loguru import logger
from sqlalchemy import delete, update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import Wallet
from app.models.wallet_transaction import WalletTransaction, TransactionType
from app.models.order import Order
from app.models.position import Position
from app.models.grid_bot import GridBot
from app.models.task import TaskTicket
from app.models.strategy import Strategy, StrategyLog, TradeMemory
from app.models.autopilot_log import AutopilotLog
from app.models.news import NewsAlert, NewsThinking
from app.models.agent import ChatConversation, ChatMessage
from app.models.trend_scheme import TrendScheme, TrendSnapshot
from app.models.scratchpad import AnalysisScratchpad
from app.services.wallet import WalletManager


class ResetService:
    """
    账户重置服务
    
    清空 15 张表的用户数据，保留策略定义，重置钱包余额。
    """

    @staticmethod
    async def full_reset(
        db: AsyncSession,
        user_id: int,
        initial_balance: Decimal | None = None,
    ) -> Wallet:
        """
        执行完整的账户重置
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            initial_balance: 重置后初始余额 (默认从环境变量读取)
            
        Returns:
            重置后的 Wallet 对象
        """
        logger.info(f"[ResetService] User {user_id} starting full account reset...")

        # ==================== 清空所有用户数据 ====================
        
        # 1. 订单
        await db.execute(delete(Order).where(Order.user_id == user_id))
        
        # 2. 仓位
        await db.execute(delete(Position).where(Position.user_id == user_id))
        
        # 3. 网格机器人
        await db.execute(delete(GridBot).where(GridBot.user_id == user_id))
        
        # 4. AI 任务
        await db.execute(delete(TaskTicket).where(TaskTicket.user_id == user_id))
        
        # 5. 交易记忆 / 日记
        await db.execute(delete(TradeMemory).where(TradeMemory.user_id == user_id))
        
        # 6. 钱包流水
        await db.execute(delete(WalletTransaction).where(WalletTransaction.user_id == user_id))
        
        # 7. 策略日志 (先删日志再删策略，外键依赖)
        user_strategy_ids = (
            await db.execute(
                select(Strategy.id).where(Strategy.user_id == user_id)
            )
        ).scalars().all()
        if user_strategy_ids:
            await db.execute(
                delete(StrategyLog).where(StrategyLog.strategy_id.in_(user_strategy_ids))
            )
        
        # 8. 策略保留定义，只清日志
        
        # 9. 自动交易日志
        await db.execute(delete(AutopilotLog).where(AutopilotLog.user_id == user_id))
        
        # 10. 新闻 AI 思考记录
        await db.execute(delete(NewsThinking).where(NewsThinking.user_id == user_id))
        
        # 11. 新闻监控规则
        await db.execute(delete(NewsAlert).where(NewsAlert.user_id == user_id))
        
        # 12. AI 对话消息 (先删消息再删会话)
        user_conv_ids = (
            await db.execute(
                select(ChatConversation.id).where(ChatConversation.user_id == user_id)
            )
        ).scalars().all()
        if user_conv_ids:
            await db.execute(
                delete(ChatMessage).where(ChatMessage.conversation_id.in_(user_conv_ids))
            )
        await db.execute(delete(ChatConversation).where(ChatConversation.user_id == user_id))
        
        # 13. 趋势分析快照
        user_scheme_ids = (
            await db.execute(
                select(TrendScheme.id).where(TrendScheme.user_id == user_id)
            )
        ).scalars().all()
        if user_scheme_ids:
            await db.execute(
                delete(TrendSnapshot).where(TrendSnapshot.scheme_id.in_(user_scheme_ids))
            )
        
        # 14. 重置趋势方案缓存 (保留方案本身，清空结果)
        await db.execute(
            update(TrendScheme).where(TrendScheme.user_id == user_id).values(
                last_result=None,
                last_run_at=None,
            )
        )
        
        # 15. AI 分析记事本
        await db.execute(delete(AnalysisScratchpad).where(AnalysisScratchpad.user_id == user_id))
        
        logger.info(f"[ResetService] User {user_id}: cleared 15 tables")

        # ==================== 重置钱包 ====================
        initial = initial_balance or Decimal(
            os.getenv("SIMULATION_INITIAL_BALANCE", "100")
        )
        
        wallet = await WalletManager.get_wallet(db, user_id)
        if not wallet:
            wallet = await WalletManager.initialize_wallet(db, user_id)
        
        old_balance = wallet.balance + wallet.frozen
        
        wallet.balance = initial
        wallet.frozen = Decimal("0")
        wallet.total_pnl = Decimal("0")
        
        # 记录重置流水
        tx = WalletTransaction(
            user_id=user_id,
            type=TransactionType.RESET.value,
            amount=initial,
            balance_after=initial,
            note=f"Full account reset to {initial} USDT (was {old_balance} USDT)",
        )
        db.add(tx)
        
        try:
            await db.commit()
            await db.refresh(wallet)
        except Exception as e:
            await db.rollback()
            logger.error(f"[ResetService] Reset failed for user {user_id}: {e}")
            raise
        
        logger.info(
            f"[ResetService] User {user_id} account fully reset to {initial} USDT "
            f"(strategies preserved)"
        )
        return wallet
