"""
Memory Consolidator — 董事会记忆坍缩引擎
==========================================
每日自动将交易日志+AI辩论记录压缩为精炼《董事会纪要》。

职责:
1. 定时触发 (每天 UTC+8 00:05)
2. 抽取当日 orders + hub_logs + autopilot_logs
3. 调用"书记员" AI 生成纪要
4. 存入 board_minutes 表
5. 支持手动触发 (CEO 一键生成)
"""

import asyncio
import json
from datetime import datetime, date, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now


# 北京时区
_CST = timezone(timedelta(hours=8))


def _decrypt_agent_key(encrypted: str) -> str:
    """解密 Agent 的 API Key — 自动兼容多种加密格式"""
    if not encrypted:
        return ""
    
    # 方法 1: Fernet 解密
    try:
        from app.core.encryption import decrypt_api_key
        return decrypt_api_key(encrypted)
    except Exception:
        pass
    
    # 方法 2: Base64 解密 (hub.py 的 fallback 可能使用了 base64)
    try:
        import base64
        decoded = base64.b64decode(encrypted.encode()).decode()
        # 验证解出来的看起来像 API Key (非空且可打印)
        if decoded and decoded.isprintable() and len(decoded) > 5:
            return decoded
    except Exception:
        pass
    
    # 方法 3: 原始值 (可能未加密直接存储)
    if encrypted.startswith("sk-") or len(encrypted) > 20:
        return encrypted
    
    raise ValueError(f"无法解密 API Key (长度={len(encrypted)})")

# 华尔街级书记员 System Prompt
_SECRETARY_PROMPT = """你是一位顶级对冲基金的首席合规与复盘官。你的任务是根据提供的今日系统原始数据，生成一份极度结构化的硬核复盘报告。

必须包含以下模块（缺失数据的模块写"无数据"即可）：

1.【核心数据】：总交易笔数、胜率（盈利笔数/总笔数）、净盈亏、最大单笔盈利/亏损、资金费率消耗、最大回撤。用数据说话，不要空泛描述。

2.【交易时间轴】：列出每笔交易的精确时间（北京时间）、标的、方向、杠杆、入场价/出场价、持仓时长、触发逻辑与最终盈亏结果。

3.【被阻拦的交易】：列出今日AI想执行但被风控/系统阻拦的交易决策。分析这些被拦截的交易如果执行了，结果会如何——是正确的拦截还是错失的机会？

4.【AI 逻辑审计】：审查今日各 Agent 的决策过程。只关注决策质量，不需要展开技术指标的具体数值（如MACD、RSI、布林线等的计算过程）。重点指出：
   - 优秀的预判（提前捕捉到信号的决策）
   - 冲动或草率的决策（缺乏充分分析就下单）
   - 逻辑错误（判断方向与最终走势矛盾）
   - 错失的机会（有明确信号但未行动）

5.【市场情绪与环境】：分析当天市场的整体情绪、重大外部事件或政策变化对行情的影响，以及AI系统是否适应了这种市场环境变化。

6.【系统健康教训】：总结今日得失的核心问题和逻辑缺陷，给出明日具体的优化方向。避免每次重复"降低杠杆、降低频率"等泛泛建议——除非确实发现了相关问题。

重要规则：
- 全程中文，专业但易懂
- 精简技术指标细节，只概述AI的决策依据，不罗列MACD、布林通道等具体计算值
- 没有交易时照实说"今日无交易"，但仍需审计 AI 的分析质量
- 给出重要性评分 (1-10)，基于当日市场波动和决策质量

输出格式 (严格 JSON):
{
    "summary": "完整复盘报告正文（包含上述6个模块）...",
    "key_lessons": "一句话核心教训",
    "importance": 7
}
"""


class MemoryConsolidator:
    """记忆坍缩引擎"""
    
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """启动定时调度 + 启动时补执行"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._daily_loop())
        logger.info("[MemoryConsolidator] Started (daily @ 00:05 CST)")
        
        # ★ 启动时补执行：检查昨天是否有纪要，没有则补生成
        asyncio.create_task(self._startup_catchup())
    
    async def _startup_catchup(self):
        """启动时检查昨天的纪要是否存在，不存在则补生成"""
        await asyncio.sleep(30)  # 等待系统完全启动
        try:
            from app.db.session import AsyncSessionLocal
            from app.models.board_minutes import BoardMinutes
            from app.models.hub_agent import HubAgent
            
            yesterday = (datetime.now(_CST) - timedelta(days=1)).date()
            
            async with AsyncSessionLocal() as db:
                # 获取所有有 Agent 的用户
                user_result = await db.execute(select(HubAgent.user_id).distinct())
                user_ids = [uid for (uid,) in user_result.all()]
                
                for user_id in user_ids:
                    # 检查昨天是否已有纪要
                    existing = await db.execute(
                        select(BoardMinutes.id).where(
                            BoardMinutes.user_id == user_id,
                            BoardMinutes.date == yesterday,
                        )
                    )
                    if not existing.scalar_one_or_none():
                        # ★ 自动从 Redis 获取用户设定的书记员
                        secretary_id = await self._get_secretary_from_redis(user_id)
                        logger.info(
                            f"[MemoryConsolidator] Catchup: generating yesterday's "
                            f"minutes ({yesterday}) for user {user_id}, secretary={secretary_id}"
                        )
                        try:
                            await self.consolidate(user_id, target_date=yesterday, secretary_agent_id=secretary_id)
                        except Exception as e:
                            logger.error(f"[MemoryConsolidator] Catchup failed for user {user_id}: {e}")
        except Exception as e:
            logger.error(f"[MemoryConsolidator] Startup catchup error: {e}")
    
    async def stop(self):
        """停止"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
    
    async def _daily_loop(self):
        """每日循环：等到 00:05 CST 执行"""
        while self._running:
            try:
                # 计算到下一个 00:05 的等待秒数
                now = datetime.now(_CST)
                target = now.replace(hour=0, minute=5, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                wait_seconds = (target - now).total_seconds()
                
                logger.info(
                    f"[MemoryConsolidator] Next run in {wait_seconds/3600:.1f}h "
                    f"(at {target.strftime('%Y-%m-%d %H:%M')} CST)"
                )
                await asyncio.sleep(wait_seconds)
                
                # 执行坍缩
                logger.info("[MemoryConsolidator] ★ Daily cron triggered, starting consolidation...")
                await self._run_for_all_users()
                logger.info("[MemoryConsolidator] ★ Daily consolidation complete.")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MemoryConsolidator] Loop error: {e}")
                await asyncio.sleep(3600)  # 出错等1小时重试
    
    async def _run_for_all_users(self):
        """为所有有活跃 Agent 的用户执行坍缩"""
        from app.db.session import AsyncSessionLocal
        from app.models.hub_agent import HubAgent
        
        async with AsyncSessionLocal() as db:
            # 查找所有有 hub agent 的用户
            result = await db.execute(
                select(HubAgent.user_id).distinct()
            )
            user_ids = [uid for (uid,) in result.all()]
        
        for user_id in user_ids:
            try:
                # ★ 自动从 Redis 获取用户设定的书记员
                secretary_id = await self._get_secretary_from_redis(user_id)
                logger.info(f"[MemoryConsolidator] Running for user {user_id}, secretary={secretary_id}")
                await self.consolidate(user_id, secretary_agent_id=secretary_id)
            except Exception as e:
                logger.error(f"[MemoryConsolidator] Failed for user {user_id}: {e}")
    
    @staticmethod
    async def _get_secretary_from_redis(user_id: int) -> Optional[int]:
        """从 Redis 获取用户设定的书记员 Agent ID"""
        try:
            from app.core.redis import get_redis
            r = await get_redis()
            val = await r.get(f"hub:secretary:{user_id}")
            if val:
                return int(val)
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] Failed to get secretary from Redis for user {user_id}: {e}")
        
        # ★ Fallback: 查找第一个有 API Key 的 Agent 作为书记员
        try:
            from app.db.session import AsyncSessionLocal
            from app.models.hub_agent import HubAgent
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(HubAgent.id).where(
                        HubAgent.user_id == user_id,
                        HubAgent.api_key_enc.isnot(None),
                        HubAgent.api_key_enc != '',
                    ).limit(1)
                )
                agent_id = result.scalar_one_or_none()
                if agent_id:
                    logger.info(f"[MemoryConsolidator] Fallback: using agent #{agent_id} as secretary for user {user_id}")
                    return agent_id
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] Fallback secretary lookup failed: {e}")
        
        return None
    
    async def consolidate(
        self,
        user_id: int,
        target_date: Optional[date] = None,
        secretary_agent_id: Optional[int] = None,
    ) -> dict:
        """
        核心方法: 为指定用户执行一次记忆坍缩
        
        Args:
            user_id: 用户 ID
            target_date: 目标日期 (默认今天)
            secretary_agent_id: 指定书记员 Agent ID (使用该 Agent 的模型和 API Key)
        
        Returns:
            生成的纪要字典
        """
        from app.db.session import AsyncSessionLocal
        
        if target_date is None:
            target_date = datetime.now(_CST).date()
        
        logger.info(f"[MemoryConsolidator] Consolidating for user {user_id}, date {target_date}, secretary={secretary_agent_id}")
        
        async with AsyncSessionLocal() as db:
            # 1. 抽取数据
            trades_text = await self._extract_trades(db, user_id, target_date)
            ai_debate_text = await self._extract_hub_logs(db, user_id, target_date)
            autopilot_text = await self._extract_autopilot(db, user_id, target_date)
            blocked_trades_text = await self._extract_blocked_trades(db, user_id, target_date)
            trade_count, pnl_total = await self._get_trade_stats(db, user_id, target_date)
            funding_costs = await self._extract_funding_costs(db, user_id, target_date)
            max_drawdown = await self._extract_max_drawdown(db, user_id, target_date)
            
            # 2. 构建书记员 prompt
            data_block = self._build_data_block(
                target_date, trades_text, ai_debate_text, autopilot_text,
                trade_count, pnl_total,
                funding_costs=funding_costs, max_drawdown=max_drawdown,
                blocked_trades=blocked_trades_text,
            )
            
            if not trades_text and not ai_debate_text and not autopilot_text:
                logger.info(f"[MemoryConsolidator] No data for user {user_id} on {target_date}")
                summary = f"{target_date} 无交易活动，无辩论记录。系统平静运行。"
                result = {
                    "summary": summary,
                    "key_lessons": "今日无事。",
                    "importance": 1,
                }
            else:
                # 3. 调用 AI (优先使用指定书记员 Agent)
                result = await self._call_secretary_ai(
                    db, user_id, data_block,
                    secretary_agent_id=secretary_agent_id,
                )
            
            # 4. 存入数据库
            await self._save_minutes(
                db, user_id, target_date, result,
                trade_count, pnl_total,
            )
            await db.commit()
        
        logger.info(f"[MemoryConsolidator] Minutes saved for user {user_id}, date {target_date}")
        return result
    
    # Hub 下单的 source 白名单 — 统计所有 AI 发起的操作
    _HUB_SOURCES = ('agent', 'hub', 'hub_board', 'autopilot', 'autopilot_reflection')
    
    async def _extract_trades(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> str:
        """从 positions 表抽取当日详细交易时间轴（入场/出场时间 + 成交价 + 手续费）"""
        from app.models.position import Position, PositionStatus, PositionSide
        
        # 北京时间当天 → UTC 范围 (CST = UTC+8)
        day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
        day_end = day_start + timedelta(days=1)
        
        try:
            from sqlalchemy import or_
            result = await db.execute(
                select(Position).where(
                    Position.user_id == user_id,
                    or_(
                        and_(Position.created_at >= day_start, Position.created_at < day_end),
                        and_(Position.closed_at >= day_start, Position.closed_at < day_end),
                    ),
                ).order_by(Position.created_at)
            )
            positions = result.scalars().all()
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] extract_trades error: {e}")
            return ""
        
        if not positions:
            return ""
        
        # 获取实时价格用于计算 OPEN 仓位浮动盈亏
        live_prices = {}
        try:
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            symbols = set(p.symbol for p in positions if p.status == PositionStatus.OPEN)
            for sym in symbols:
                ticker = await client.get_ticker(sym)
                if ticker:
                    live_prices[sym] = float(ticker.get("lastPrice", 0))
        except Exception:
            pass
        
        def _to_cst(dt):
            """UTC datetime → CST 字符串"""
            if not dt:
                return "-"
            return (dt + timedelta(hours=8)).strftime("%H:%M:%S")
        
        lines = []
        for p in positions:
            side_str = p.side.value.upper() if hasattr(p.side, 'value') else str(p.side).upper()
            leverage = p.leverage or 1
            entry_price = float(p.entry_price) if p.entry_price else 0
            commission = float(p.total_commission) if p.total_commission else 0
            source = p.source or "unknown"
            open_time = _to_cst(p.created_at)
            open_reason = getattr(p, 'open_reason', '') or ''
            
            if p.status == PositionStatus.CLOSED:
                pnl = float(p.realized_pnl) if p.realized_pnl else 0
                # 反算出场价: Position 模型没有 close_price, 从 pnl 反推
                close_price = 0.0
                size_f = float(p.size) if p.size else 0
                if size_f > 0 and entry_price > 0:
                    side_val = p.side.value if hasattr(p.side, 'value') else str(p.side)
                    if side_val == 'long':
                        close_price = entry_price + pnl / size_f
                    else:
                        close_price = entry_price - pnl / size_f
                close_time = _to_cst(p.closed_at)
                # 计算持仓时长
                if p.created_at and p.closed_at:
                    duration_min = int((p.closed_at - p.created_at).total_seconds() / 60)
                    if duration_min > 60:
                        duration_str = f"{duration_min // 60}h{duration_min % 60}m"
                    else:
                        duration_str = f"{duration_min}m"
                else:
                    duration_str = "-"
                pnl_sign = '+' if pnl >= 0 else ''
                lines.append(
                    f"- [{open_time}] {p.symbol} {side_str} {p.size} {leverage}x | "
                    f"入场{entry_price:.1f} → 出场{close_price:.1f} | "
                    f"持仓{duration_str} | 盈亏{pnl_sign}{pnl:.2f} USDT | "
                    f"手续费{commission:.4f} | [{source}]"
                    + (f" | 原因: {open_reason[:80]}" if open_reason else "")
                )
            else:
                mark = live_prices.get(p.symbol, 0)
                if mark > 0:
                    from decimal import Decimal
                    unrealized = float(p.calculate_unrealized_pnl(Decimal(str(mark))))
                    pnl_str = f"浮盈{'+' if unrealized >= 0 else ''}{unrealized:.2f}"
                else:
                    pnl_str = "浮盈未知"
                lines.append(
                    f"- [{open_time}] {p.symbol} {side_str} {p.size} {leverage}x | "
                    f"入场{entry_price:.1f} | 持仓中 {pnl_str} USDT | [{source}]"
                )
        
        return "\n".join(lines)
    
    async def _extract_hub_logs(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> str:
        """从 hub_logs 表抽取当日 AI 发言（分 Agent 分组，内容截断提至 500 字）"""
        from app.models.hub_log import HubLog
        from collections import defaultdict
        
        day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
        day_end = day_start + timedelta(days=1)
        
        result = await db.execute(
            select(HubLog).where(
                HubLog.user_id == user_id,
                HubLog.created_at >= day_start,
                HubLog.created_at < day_end,
                HubLog.log_type == "ai_text",
            ).order_by(HubLog.created_at).limit(60)
        )
        logs = result.scalars().all()
        
        if not logs:
            return ""
        
        # 按 Agent 分组
        by_agent = defaultdict(list)
        for lg in logs:
            name = lg.agent_name or "Unknown"
            content = lg.content  # 完整保留内容
            time_str = (lg.created_at + timedelta(hours=8)).strftime("%H:%M") if lg.created_at else ""
            by_agent[name].append(f"  [{time_str}] {content}")
        
        sections = []
        for agent_name, entries in by_agent.items():
            sections.append(f"### {agent_name} ({len(entries)} 条发言)")
            # 每个 Agent 最多取最后 8 条（保留最新的分析）
            for entry in entries[-8:]:
                sections.append(entry)
        
        return "\n".join(sections)
    
    async def _extract_autopilot(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> str:
        """从 autopilot_logs 表抽取当日决策"""
        try:
            from app.models.autopilot_log import AutopilotLog
            
            # 北京时间当天 → UTC 范围
            day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
            day_end = day_start + timedelta(days=1)
            
            result = await db.execute(
                select(AutopilotLog).where(
                    AutopilotLog.user_id == user_id,
                    AutopilotLog.created_at >= day_start,
                    AutopilotLog.created_at < day_end,
                ).order_by(AutopilotLog.created_at).limit(20)
            )
            logs = result.scalars().all()
            
            if not logs:
                return ""
            
            lines = []
            for lg in logs:
                lines.append(f"- {lg.symbol} 决策={lg.decision} | {lg.summary[:100]}")
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] extract_autopilot error: {e}")
            return ""
    
    async def _extract_blocked_trades(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> str:
        """从 autopilot_logs 表提取被阻拦的交易（AI想执行但未成功执行的决策）"""
        try:
            from app.models.autopilot_log import AutopilotLog
            
            day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
            day_end = day_start + timedelta(days=1)
            
            result = await db.execute(
                select(AutopilotLog).where(
                    AutopilotLog.user_id == user_id,
                    AutopilotLog.created_at >= day_start,
                    AutopilotLog.created_at < day_end,
                    AutopilotLog.action_taken == False,
                    AutopilotLog.decision.notin_(["hold", "error"]),
                ).order_by(AutopilotLog.created_at).limit(20)
            )
            logs = result.scalars().all()
            
            if not logs:
                return ""
            
            def _to_cst(dt):
                if not dt:
                    return "-"
                return (dt + timedelta(hours=8)).strftime("%H:%M:%S")
            
            lines = []
            for lg in logs:
                time_str = _to_cst(lg.created_at)
                decision_map = {
                    "open_long": "想做多", "open_short": "想做空",
                    "close_long": "想平多", "close_short": "想平空",
                }
                decision_cn = decision_map.get(lg.decision, lg.decision)
                error = f" | 原因: {lg.error_message[:100]}" if lg.error_message else ""
                summary = lg.summary[:150] if lg.summary else ""
                lines.append(f"- [{time_str}] {lg.symbol} {decision_cn} | {summary}{error}")
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] extract_blocked_trades error: {e}")
            return ""
    
    async def _get_trade_stats(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> tuple:
        """获取当日 Hub 交易统计（基于 Position 表，源隔离 + 真实盈亏）"""
        from app.models.position import Position, PositionStatus
        
        # 北京时间当天 → UTC 范围
        day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
        day_end = day_start + timedelta(days=1)
        
        try:
            from sqlalchemy import or_
            
            # 当日 Hub 产生的仓位数
            count_result = await db.execute(
                select(func.count(Position.id)).where(
                    Position.user_id == user_id,
                    Position.source.in_(self._HUB_SOURCES),
                    or_(
                        and_(Position.created_at >= day_start, Position.created_at < day_end),
                        and_(Position.closed_at >= day_start, Position.closed_at < day_end),
                    ),
                )
            )
            trade_count = int(count_result.scalar() or 0)
            
            # 当日 Hub 已平仓仓位的已实现盈亏
            pnl_result = await db.execute(
                select(
                    func.coalesce(func.sum(Position.realized_pnl), 0),
                ).where(
                    Position.user_id == user_id,
                    Position.source.in_(self._HUB_SOURCES),
                    Position.status == PositionStatus.CLOSED,
                    Position.closed_at >= day_start,
                    Position.closed_at < day_end,
                )
            )
            pnl_total = float(pnl_result.scalar() or 0)
            
            return trade_count, pnl_total
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] get_trade_stats error: {e}")
            return 0, 0.0
    
    # ======== 资金异动采集 ========
    
    async def _extract_funding_costs(self, db: AsyncSession, user_id: int, d: date) -> str:
        """从 wallet_transactions 抽取当日资金费率消耗"""
        try:
            from app.models.wallet_transaction import WalletTransaction, TransactionType
            
            day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
            day_end = day_start + timedelta(days=1)
            
            result = await db.execute(
                select(WalletTransaction).where(
                    WalletTransaction.user_id == user_id,
                    WalletTransaction.type == TransactionType.FUNDING,
                    WalletTransaction.created_at >= day_start,
                    WalletTransaction.created_at < day_end,
                ).order_by(WalletTransaction.created_at)
            )
            txs = result.scalars().all()
            
            if not txs:
                return "当日无资金费率消耗。"
            
            total = sum(float(tx.amount) for tx in txs)
            lines = [f"资金费率总消耗: {total:+.4f} USDT ({len(txs)} 笔)"]
            for tx in txs:
                time_str = (tx.created_at + timedelta(hours=8)).strftime("%H:%M") if tx.created_at else ""
                lines.append(f"  [{time_str}] {float(tx.amount):+.4f} USDT | {tx.note or ''}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] extract_funding_costs error: {e}")
            return ""
    
    async def _extract_max_drawdown(self, db: AsyncSession, user_id: int, d: date) -> str:
        """从 wallet_transactions 的 balance_after 计算当日最大回撤"""
        try:
            from app.models.wallet_transaction import WalletTransaction
            
            day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
            day_end = day_start + timedelta(days=1)
            
            result = await db.execute(
                select(WalletTransaction.balance_after).where(
                    WalletTransaction.user_id == user_id,
                    WalletTransaction.created_at >= day_start,
                    WalletTransaction.created_at < day_end,
                ).order_by(WalletTransaction.created_at)
            )
            balances = [float(row[0]) for row in result.all()]
            
            if len(balances) < 2:
                return "当日资金变动不足，无法计算回撤。"
            
            # 计算最大回撤
            peak = balances[0]
            max_dd = 0
            for b in balances:
                if b > peak:
                    peak = b
                dd = peak - b
                if dd > max_dd:
                    max_dd = dd
            
            dd_pct = (max_dd / peak * 100) if peak > 0 else 0
            return f"最大回撤: {max_dd:.2f} USDT ({dd_pct:.2f}%) | 日初余额: {balances[0]:.2f} | 日末余额: {balances[-1]:.2f}"
        except Exception as e:
            logger.warning(f"[MemoryConsolidator] extract_max_drawdown error: {e}")
            return ""
    
    # ======== 书记员 AI ========
    
    def _build_data_block(
        self, d: date, trades: str, debates: str, autopilot: str,
        trade_count: int, pnl_total: float,
        funding_costs: str = "", max_drawdown: str = "",
        blocked_trades: str = "",
    ) -> str:
        """拼接结构化数据块给书记员"""
        parts = [
            f"# 今日系统原始数据 — {d}",
            f"\n## 概览",
            f"交易笔数: {trade_count} | 总盈亏: {pnl_total:+.2f} USDT",
        ]
        
        # 交易时间轴
        parts.append(f"\n## 交易时间轴")
        if trades:
            parts.append(trades)
        else:
            parts.append("今日无交易。")
        
        # 被阻拦的交易
        parts.append(f"\n## 被阻拦的交易（AI想执行但被系统/风控拦截的决策）")
        if blocked_trades:
            parts.append(blocked_trades)
        else:
            parts.append("今日无被阻拦的交易。")
        
        # 资金异动
        parts.append(f"\n## 资金异动")
        if max_drawdown:
            parts.append(max_drawdown)
        if funding_costs:
            parts.append(funding_costs)
        
        # AI 决策逻辑
        if debates:
            parts.append(f"\n## AI 决策逻辑源（各 Agent 当日分析原文）")
            parts.append(debates)
        
        # Autopilot 决策
        if autopilot:
            parts.append(f"\n## Autopilot 自动决策")
            parts.append(autopilot)
        
        return "\n".join(parts)
    
    async def _call_secretary_ai(
        self, db: AsyncSession, user_id: int, data_block: str,
        secretary_agent_id: Optional[int] = None,
    ) -> dict:
        """调用 AI 生成纪要 (使用指定书记员 Agent 的 Key)"""
        import openai
        
        api_key = None
        base_url = "https://api.deepseek.com"  # 默认 (无 /v1, SDK 自动处理)
        model = "deepseek-chat"
        
        # 使用指定书记员 Agent 的配置 — 谁当书记员就用谁的 Key
        if secretary_agent_id:
            from app.models.hub_agent import HubAgent
            agent_result = await db.execute(
                select(HubAgent).where(HubAgent.id == secretary_agent_id)
            )
            agent = agent_result.scalar_one_or_none()
            if agent:
                model = agent.model or "deepseek-chat"
                if agent.api_key_enc:
                    try:
                        api_key = _decrypt_agent_key(agent.api_key_enc)
                    except Exception as e:
                        logger.error(
                            f"[MemoryConsolidator] FAILED to decrypt API key for "
                            f"secretary agent #{secretary_agent_id} ({agent.name}): {e}"
                        )
                        return {
                            "summary": f"书记员 {agent.name} 的 API Key 解密失败，请重新配置该 Agent 的 Key。",
                            "key_lessons": "API Key 配置异常。",
                            "importance": 3,
                        }
                else:
                    logger.warning(
                        f"[MemoryConsolidator] Secretary agent #{secretary_agent_id} "
                        f"({agent.name}) has no API key configured"
                    )
                    return {
                        "summary": f"书记员 {agent.name} 未配置 API Key，请在 Agent 设置中填入。",
                        "key_lessons": "请为书记员 Agent 配置 API Key。",
                        "importance": 3,
                    }
                if agent.api_base_url:
                    base_url = agent.api_base_url
                    # 不再强制追加 /v1, 用户自定义 URL 原样使用
                elif agent.provider == "ollama":
                    base_url = "http://localhost:11434/v1"  # Ollama 需要 /v1 仅限 OpenAI 兼容模式
                logger.info(
                    f"[MemoryConsolidator] Using secretary agent #{secretary_agent_id} "
                    f"({agent.name}), model={model}"
                )
            else:
                logger.warning(
                    f"[MemoryConsolidator] Secretary agent #{secretary_agent_id} not found"
                )
        
        if not api_key:
            logger.warning("[MemoryConsolidator] No API key available, using fallback summary")
            return {
                "summary": f"无法生成纪要（未指定书记员或缺少 API Key）。当日数据:\n{data_block[:200]}",
                "key_lessons": "请指定一个配有 API Key 的书记员 Agent。",
                "importance": 3,
            }
        
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SECRETARY_PROMPT},
                    {"role": "user", "content": data_block},
                ],
                temperature=0.3,
                max_tokens=8192,  # ★ 支持长篇结构化复盘报告
            )
            content = response.choices[0].message.content or ""
            
            # 尝试解析 JSON
            try:
                # 提取 JSON 块
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                parsed = json.loads(content)
                return {
                    "summary": parsed.get("summary", content),
                    "key_lessons": parsed.get("key_lessons", ""),
                    "importance": int(parsed.get("importance", 5)),
                }
            except (json.JSONDecodeError, ValueError):
                # JSON 解析失败，用原始文本
                return {
                    "summary": content,
                    "key_lessons": "",
                    "importance": 5,
                }
        
        except Exception as e:
            logger.error(f"[MemoryConsolidator] AI call failed: {e}")
            return {
                "summary": f"AI 生成失败: {str(e)[:100]}。当日数据:\n{data_block[:200]}",
                "key_lessons": "AI 调用异常。",
                "importance": 3,
            }
    
    # ======== 存储 ========
    
    async def _save_minutes(
        self,
        db: AsyncSession,
        user_id: int,
        target_date: date,
        result: dict,
        trade_count: int,
        pnl_total: float,
    ):
        """保存纪要到数据库（upsert 逻辑）"""
        from app.models.board_minutes import BoardMinutes
        
        # 查找是否已存在
        existing = await db.execute(
            select(BoardMinutes).where(
                BoardMinutes.user_id == user_id,
                BoardMinutes.date == target_date,
            )
        )
        minutes = existing.scalar_one_or_none()
        
        if minutes:
            # 更新
            minutes.summary = result["summary"]
            minutes.key_lessons = result["key_lessons"]
            minutes.importance = result["importance"]
            minutes.trade_count = trade_count
            minutes.pnl_total = pnl_total
            logger.info(f"[MemoryConsolidator] Updated existing minutes for {target_date}")
        else:
            # 新建
            minutes = BoardMinutes(
                user_id=user_id,
                date=target_date,
                summary=result["summary"],
                key_lessons=result["key_lessons"],
                importance=result["importance"],
                trade_count=trade_count,
                pnl_total=pnl_total,
            )
            db.add(minutes)
            logger.info(f"[MemoryConsolidator] Created new minutes for {target_date}")


# ======== 全局加载函数 (供 prompt 注入使用) ========

async def load_board_memory(
    db: AsyncSession,
    user_id: int,
    days: int = 3,
) -> str:
    """
    加载近 N 天的董事会纪要，格式化为注入文本。
    
    供 brain.py 和 prompts.py 调用。
    """
    from app.models.board_minutes import BoardMinutes
    
    cutoff = date.today() - timedelta(days=days)
    
    result = await db.execute(
        select(BoardMinutes).where(
            BoardMinutes.user_id == user_id,
            BoardMinutes.date >= cutoff,
        ).order_by(BoardMinutes.date.desc()).limit(days)
    )
    minutes_list = result.scalars().all()
    
    if not minutes_list:
        return ""
    
    lines = []
    for m in minutes_list:
        pnl_sign = "+" if m.pnl_total >= 0 else ""
        lines.append(
            f"【{m.date} 纪要】重要性: {m.importance}/10 | "
            f"交易 {m.trade_count} 笔 | 净盈亏: {pnl_sign}{m.pnl_total:.1f} USDT\n"
            f"{m.summary}\n"
            f"教训: {m.key_lessons}"
        )
    
    return "\n\n".join(lines)


# 全局单例
memory_consolidator = MemoryConsolidator()
