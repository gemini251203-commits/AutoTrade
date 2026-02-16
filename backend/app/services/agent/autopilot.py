"""
Agent Autopilot
================
AI Agent 自动交易模式

将"自动交易"作为 Agent 的一个模式:
- 定时触发 Agent 分析市场并决策
- 决策记录写入专属会话 (不混入手动对话)
- 复用 Agent 完整工具链 (get_price, place_order, etc.)
"""

import asyncio
from typing import Dict, Optional
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.session import AsyncSessionLocal
from app.models.agent import ChatConversation, ChatMessage
from app.services.agent.agent import chat_complete


# 间隔映射 (秒)
INTERVAL_SECONDS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
}

# Autopilot 会话标识前缀
AUTOPILOT_TITLE_PREFIX = "[autopilot]"


class AgentAutopilot:
    """
    Agent 自动交易引擎

    管理每个用户的自动决策循环,
    复用 AI Agent 的完整工具链。
    """

    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._configs: Dict[int, dict] = {}

    def is_running(self, user_id: int) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

    async def start(self, user_id: int, config: dict):
        """
        启动自动决策循环

        Args:
            user_id: 用户 ID
            config: {
                "symbols": ["BTCUSDT"],
                "interval": "15m",
            }
        """
        if self.is_running(user_id):
            logger.warning(f"[Autopilot] Already running for user {user_id}")
            return

        self._configs[user_id] = config
        task = asyncio.create_task(self._loop(user_id, config))
        self._tasks[user_id] = task
        logger.info(
            f"[Autopilot] Started for user {user_id}, "
            f"symbols={config.get('symbols')}, "
            f"interval={config.get('interval', '15m')}"
        )

    async def stop(self, user_id: int):
        """停止自动决策"""
        task = self._tasks.pop(user_id, None)
        self._configs.pop(user_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info(f"[Autopilot] Stopped for user {user_id}")

    async def run_once(self, user_id: int, symbol: str = "BTCUSDT") -> str:
        """
        手动触发一次决策

        Returns:
            AI 的回复文本
        """
        return await self._run_cycle(user_id, symbol)

    def get_status(self, user_id: int) -> dict:
        """获取运行状态"""
        running = self.is_running(user_id)
        config = self._configs.get(user_id, {})
        return {
            "running": running,
            "symbols": config.get("symbols", []),
            "interval": config.get("interval", "15m"),
        }

    # ============================================================
    # 内部方法
    # ============================================================

    async def _loop(self, user_id: int, config: dict):
        """定时循环"""
        interval = config.get("interval", "15m")
        seconds = INTERVAL_SECONDS.get(interval, 900)
        symbols = config.get("symbols", ["BTCUSDT"])

        logger.info(
            f"[Autopilot] Loop started: user={user_id}, "
            f"interval={seconds}s, symbols={symbols}"
        )

        try:
            while True:
                for symbol in symbols:
                    try:
                        await self._run_cycle(user_id, symbol)
                    except Exception as e:
                        logger.error(
                            f"[Autopilot] Cycle error: user={user_id}, "
                            f"symbol={symbol}, error={e}"
                        )
                await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            logger.info(f"[Autopilot] Loop cancelled for user {user_id}")

    async def _run_cycle(self, user_id: int, symbol: str) -> str:
        """
        单次决策周期

        1. 获取/创建 autopilot 专属会话
        2. 构造分析指令
        3. 调用 agent chat_complete (非流式)
        4. 返回 AI 回复
        """
        async with AsyncSessionLocal() as db:
            try:
                # 获取或创建 autopilot 会话
                conv_id = await self._get_or_create_conversation(db, user_id)

                # 构造分析指令
                now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                prompt = (
                    f"[Autopilot {now}] "
                    f"请分析 {symbol} 当前市场状况并做出交易决策。\n\n"
                    f"请按以下步骤操作:\n"
                    f"1. 查询 {symbol} 实时价格\n"
                    f"2. 获取技术指标\n"
                    f"3. 查看当前持仓和余额\n"
                    f"4. 查询历史交易经验\n"
                    f"5. 综合分析后给出决策: 开仓/平仓/观望\n"
                    f"6. 如果决定交易, 直接执行\n\n"
                    f"回复要简洁, 列出关键数据和理由。"
                )

                # 调用 Agent (非流式)
                reply = await chat_complete(
                    db=db,
                    user_id=user_id,
                    conversation_id=conv_id,
                    user_message=prompt,
                    persona="autopilot",
                )

                await db.commit()

                logger.info(
                    f"[Autopilot] Cycle done: user={user_id}, "
                    f"symbol={symbol}, reply_len={len(reply)}"
                )
                return reply

            except Exception as e:
                await db.rollback()
                logger.error(f"[Autopilot] run_cycle error: {e}")
                raise

    async def _get_or_create_conversation(
        self, db: AsyncSession, user_id: int
    ) -> int:
        """获取或创建 autopilot 专属会话"""
        # 查找已有的 autopilot 会话
        result = await db.execute(
            select(ChatConversation).where(
                ChatConversation.user_id == user_id,
                ChatConversation.persona == "autopilot",
            )
        )
        conv = result.scalar_one_or_none()

        if conv:
            return conv.id

        # 创建新的 autopilot 会话
        conv = ChatConversation(
            user_id=user_id,
            persona="autopilot",
            title=f"{AUTOPILOT_TITLE_PREFIX} 自动交易记录",
        )
        db.add(conv)
        await db.flush()
        logger.info(
            f"[Autopilot] Created conversation {conv.id} for user {user_id}"
        )
        return conv.id


# 全局单例
autopilot = AgentAutopilot()
