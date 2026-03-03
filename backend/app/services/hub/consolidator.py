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

# 书记员 System Prompt
_SECRETARY_PROMPT = """你是董事会书记员。你的任务是根据今天的交易记录和 AI 辩论记录，写一份精炼的《董事会纪要》。

要求:
1. 点名指出哪个 AI 提出了什么观点
2. 总结最终做出了什么决策
3. 标明每笔交易赚了还是亏了
4. 提炼出一条核心教训
5. 给出重要性评分 (1-10)
6. 全文字数严格控制在 300 字以内
7. 全程中文

输出格式 (严格 JSON):
{
    "summary": "今日纪要正文...",
    "key_lessons": "核心教训一句话",
    "importance": 7
}
"""


class MemoryConsolidator:
    """记忆坍缩引擎"""
    
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """启动定时调度"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._daily_loop())
        logger.info("[MemoryConsolidator] Started (daily @ 00:05 CST)")
    
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
                await self._run_for_all_users()
                
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
                await self.consolidate(user_id)
            except Exception as e:
                logger.error(f"[MemoryConsolidator] Failed for user {user_id}: {e}")
    
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
            trade_count, pnl_total = await self._get_trade_stats(db, user_id, target_date)
            
            # 2. 构建书记员 prompt
            data_block = self._build_data_block(
                target_date, trades_text, ai_debate_text, autopilot_text,
                trade_count, pnl_total,
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
        """从 positions 表抽取当日 Hub 相关的仓位变动（源隔离 + 真实盈亏）"""
        from app.models.position import Position, PositionStatus, PositionSide
        
        # 北京时间当天 → UTC 范围 (CST = UTC+8)
        day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
        day_end = day_start + timedelta(days=1)
        
        try:
            # 1. 当日 Agent Hub 产生的所有仓位（开仓 OR 平仓）
            from sqlalchemy import or_
            result = await db.execute(
                select(Position).where(
                    Position.user_id == user_id,
                    Position.source.in_(self._HUB_SOURCES),
                    or_(
                        # 当日开仓的
                        and_(Position.created_at >= day_start, Position.created_at < day_end),
                        # 当日平仓的
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
        
        lines = []
        for p in positions:
            side_str = p.side.value.upper() if hasattr(p.side, 'value') else str(p.side).upper()
            leverage = p.leverage or 1
            
            if p.status == PositionStatus.CLOSED:
                # 已平仓 → 已实现盈亏
                pnl = float(p.realized_pnl) if p.realized_pnl else 0
                pnl_str = f" → 已平仓 {'+' if pnl >= 0 else ''}{pnl:.2f} USDT"
                lines.append(f"- {p.symbol} {side_str} {p.size} 杠杆{leverage}x{pnl_str} [来源:{p.source}]")
            else:
                # 仍持仓 → 浮动盈亏
                mark = live_prices.get(p.symbol, 0)
                if mark > 0:
                    from decimal import Decimal
                    unrealized = float(p.calculate_unrealized_pnl(Decimal(str(mark))))
                    pnl_str = f" → 持仓中 浮盈{'+' if unrealized >= 0 else ''}{unrealized:.2f} USDT"
                else:
                    pnl_str = " → 持仓中 (无实时价)"
                lines.append(f"- {p.symbol} {side_str} {p.size} 杠杆{leverage}x{pnl_str} [来源:{p.source}]")
        
        return "\n".join(lines)
    
    async def _extract_hub_logs(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> str:
        """从 hub_logs 表抽取当日 AI 发言"""
        from app.models.hub_log import HubLog
        
        # 北京时间当天 → UTC 范围
        day_start = datetime(d.year, d.month, d.day) - timedelta(hours=8)
        day_end = day_start + timedelta(days=1)
        
        result = await db.execute(
            select(HubLog).where(
                HubLog.user_id == user_id,
                HubLog.created_at >= day_start,
                HubLog.created_at < day_end,
                HubLog.log_type == "ai_text",
            ).order_by(HubLog.created_at).limit(30)
        )
        logs = result.scalars().all()
        
        if not logs:
            return ""
        
        lines = []
        for lg in logs:
            name = lg.agent_name or "Unknown"
            content = lg.content[:150]  # 截断过长内容
            lines.append(f"- {name}: \"{content}\"")
        
        return "\n".join(lines)
    
    async def _extract_autopilot(
        self, db: AsyncSession, user_id: int, d: date,
    ) -> str:
        """从 autopilot_logs 表抽取当日决策"""
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
    
    # ======== 书记员 AI ========
    
    def _build_data_block(
        self, d: date, trades: str, debates: str, autopilot: str,
        trade_count: int, pnl_total: float,
    ) -> str:
        """拼接数据块给书记员"""
        parts = [f"日期: {d}\n交易笔数: {trade_count} | 总盈亏: {pnl_total:+.2f} USDT\n"]
        
        if trades:
            parts.append(f"[今日交易]\n{trades}")
        else:
            parts.append("[今日交易]\n无交易。")
        
        if debates:
            parts.append(f"\n[AI 辩论记录]\n{debates}")
        
        if autopilot:
            parts.append(f"\n[Autopilot 自动决策]\n{autopilot}")
        
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
                max_tokens=800,
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
                    "summary": content[:500],
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
