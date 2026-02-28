"""
Hub Daemon — 智能体中枢守护进程
====================================
平行于 autopilot.py, 完全独立的调度器。

职责:
- 定时扫描 active 智能体
- 独裁者模式: 单 Agent 自主循环
- 董事会模式: 多 AI 辩论 → 执行共识

与 autopilot.py 的关系:
- 完全不修改 autopilot.py
- 智能体可通过 tools 调用 start_autopilot 间接使用老引擎
"""

import asyncio
from typing import Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hub_agent import HubAgent, HubAgentStatus
from app.core.time_utils import utc_now


class HubDaemon:
    """
    Hub 守护进程
    
    管理智能体的生命周期：启动、停止、循环执行
    """
    
    def __init__(self):
        self._agent_tasks: Dict[str, asyncio.Task] = {}  # key: "user_id:agent_id"
        self._running = False
    
    def _task_key(self, user_id: int, agent_id: int) -> str:
        return f"{user_id}:{agent_id}"
    
    async def start_agent(self, user_id: int, agent: HubAgent):
        """启动单个智能体的自主循环"""
        key = self._task_key(user_id, agent.id)
        
        # 如果已在运行, 先停止
        if key in self._agent_tasks:
            self._agent_tasks[key].cancel()
        
        task = asyncio.create_task(
            self._agent_loop(user_id, agent.id),
            name=f"hub_agent_{key}",
        )
        self._agent_tasks[key] = task
        logger.info(f"[HubDaemon] [STARTED] Agent #{agent.id} '{agent.name}' started for user {user_id}")
    
    async def stop_agent(self, user_id: int, agent_id: int):
        """停止单个智能体"""
        key = self._task_key(user_id, agent_id)
        task = self._agent_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"[HubDaemon] [STOPPED] Agent #{agent_id} stopped for user {user_id}")
    
    async def run_agent_once(
        self,
        user_id: int,
        agent: HubAgent,
        db: AsyncSession,
    ):
        """手动触发一次智能体执行"""
        await self._execute_cycle(user_id, agent, db)
    
    async def _agent_loop(self, user_id: int, agent_id: int):
        """单个智能体的自主循环"""
        interval = 60  # 默认 60 秒一个周期
        
        while True:
            try:
                from app.db.session import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    # 重新加载智能体状态
                    result = await db.execute(
                        select(HubAgent).where(HubAgent.id == agent_id)
                    )
                    agent = result.scalar_one_or_none()
                    
                    if not agent or not agent.is_active:
                        logger.info(f"[HubDaemon] Agent #{agent_id} no longer active, stopping loop")
                        break
                    
                    await self._execute_cycle(user_id, agent, db)
                    await db.commit()
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                logger.info(f"[HubDaemon] Agent #{agent_id} loop cancelled")
                break
            except Exception as e:
                logger.error(f"[HubDaemon] Agent #{agent_id} loop error: {e}")
                # 更新错误状态
                try:
                    from app.db.session import AsyncSessionLocal
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(HubAgent).where(HubAgent.id == agent_id)
                        )
                        agent = result.scalar_one_or_none()
                        if agent:
                            agent.status = HubAgentStatus.ERROR
                            agent.last_error = str(e)[:500]
                            await db.commit()
                except Exception:
                    pass
                await asyncio.sleep(30)  # 出错后等久一点
    
    async def _execute_cycle(
        self,
        user_id: int,
        agent: HubAgent,
        db: AsyncSession,
    ):
        """执行一个决策周期"""
        from app.services.hub.brain import hub_brain
        
        logger.info(f"[HubDaemon] [CYCLE] Agent #{agent.id} '{agent.name}' executing cycle")
        
        # 构建分析指令
        prompt = self._build_cycle_prompt(agent)
        
        # 调用 AI
        reply = await hub_brain.chat_once(
            agent=agent,
            message=prompt,
            db=db,
            user_id=user_id,
        )
        
        # 更新状态
        agent.total_runs += 1
        agent.last_run_at = utc_now()
        
        if "[ERROR]" in reply:
            agent.last_error = reply[:500]
        else:
            agent.last_error = None
        
        # 检查是否产生了交易
        if any(kw in reply for kw in ["order_id", "订单已", "已下单", "已平仓"]):
            agent.total_trades += 1
        
        logger.info(
            f"[HubDaemon] Agent #{agent.id} cycle done. "
            f"Runs={agent.total_runs}, Trades={agent.total_trades}"
        )
    
    def _build_cycle_prompt(self, agent: HubAgent) -> str:
        """构建自主决策周期的 prompt"""
        return (
            "请进行一次完整的市场分析和交易决策。\n\n"
            "执行步骤:\n"
            "1. 调用 get_balance 查看账户状态\n"
            "2. 调用 get_positions 查看当前持仓\n"
            "3. 调用 get_price 获取 BTCUSDT 最新价格\n"
            "4. 调用 get_indicators 获取技术指标\n"
            "5. 基于以上数据，决定是否需要交易\n"
            "6. 如果有明确信号，调用 place_order 执行交易\n"
            "7. 给出简要的分析报告\n\n"
            "注意: 如果没有明确信号，选择 HOLD 观望即可。不要强行交易。"
        )
    
    def get_running_agents(self) -> list:
        """获取当前运行中的智能体列表"""
        return [
            key for key, task in self._agent_tasks.items()
            if not task.done()
        ]


# 全局单例
hub_daemon = HubDaemon()
