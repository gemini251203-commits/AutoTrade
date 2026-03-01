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
        interval = 300  # 每5分钟巡逻一次
        consecutive_errors = 0
        MAX_CONSECUTIVE_FATAL = 3  # 连续致命错误 N 次后熔断
        
        # 不可恢复的致命关键词 (这些错误再重试也没用)
        FATAL_KEYWORDS = [
            'insufficient', 'balance', 'billing', 'quota', 'exceeded',
            'invalid api key', 'invalid_api_key', 'api key not valid',
            'account deactivated', 'account suspended', 'deactivated',
            'permission denied', 'forbidden',
        ]
        
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
                    
                    # ★ 自愈机制: 成功执行后重置错误计数
                    consecutive_errors = 0
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                logger.info(f"[HubDaemon] Agent #{agent_id} loop cancelled")
                break
            except Exception as e:
                err_str = str(e).lower()
                err_detail = str(e)[:500]
                
                # 判断是否为致命错误 (不可自动恢复)
                is_fatal = any(kw in err_str for kw in FATAL_KEYWORDS)
                # 瞬态: timeout/连接/SSL 等
                is_transient = not is_fatal and any(kw in err_str for kw in [
                    '401', 'unauthorized', 'timeout', 'timed out',
                    'connect', 'connection', 'refused', 'reset',
                    'ssl', 'eof', 'broken pipe',
                ])
                
                if is_fatal:
                    consecutive_errors += 1
                
                # ★ 推送错误到 hub_logs (前端可见)
                try:
                    from app.db.session import AsyncSessionLocal
                    from app.models.hub_log import HubLog
                    async with AsyncSessionLocal() as err_db:
                        result = await err_db.execute(
                            select(HubAgent).where(HubAgent.id == agent_id)
                        )
                        agent = result.scalar_one_or_none()
                        agent_name = agent.name if agent else f"Agent #{agent_id}"
                        
                        if is_fatal:
                            log_content = f"[🔴 致命错误] {agent_name}: {err_detail}"
                        elif is_transient:
                            log_content = f"[⚠️ 瞬态错误] {agent_name}: {err_detail} (将自动重试)"
                        else:
                            log_content = f"[❌ 运行错误] {agent_name}: {err_detail}"
                        
                        err_db.add(HubLog(
                            user_id=user_id,
                            agent_id=agent_id,
                            agent_name=agent_name,
                            log_type="error",
                            content=log_content,
                        ))
                        
                        # 致命错误: 标红 + 熔断
                        if is_fatal and agent:
                            agent.status = HubAgentStatus.ERROR
                            agent.last_error = err_detail
                            # 连续致命错误超过阈值 → 彻底停止
                            if consecutive_errors >= MAX_CONSECUTIVE_FATAL:
                                agent.is_active = False
                                err_db.add(HubLog(
                                    user_id=user_id,
                                    agent_id=agent_id,
                                    agent_name=agent_name,
                                    log_type="error",
                                    content=f"[⛔ 熔断] {agent_name} 连续 {consecutive_errors} 次致命错误，已自动挂起。请检查 API Key / 账户余额后手动重启。",
                                ))
                        elif not is_transient and agent:
                            agent.status = HubAgentStatus.ERROR
                            agent.last_error = err_detail
                        
                        await err_db.commit()
                except Exception as log_err:
                    logger.warning(f"[HubDaemon] Failed to save error log: {log_err}")
                
                # ★ 致命错误熔断: 真正停止循环
                if is_fatal and consecutive_errors >= MAX_CONSECUTIVE_FATAL:
                    logger.error(f"[HubDaemon] Agent #{agent_id} CIRCUIT BREAK: {consecutive_errors} consecutive fatal errors, stopping loop")
                    # 从运行列表中移除
                    key = self._task_key(user_id, agent_id)
                    self._agent_tasks.pop(key, None)
                    break
                
                if is_transient:
                    logger.warning(f"[HubDaemon] Agent #{agent_id} transient error (will retry): {e}")
                    await asyncio.sleep(15)
                    continue
                
                logger.error(f"[HubDaemon] Agent #{agent_id} loop error: {e}")
                await asyncio.sleep(30)
    
    async def _execute_cycle(
        self,
        user_id: int,
        agent: HubAgent,
        db: AsyncSession,
    ):
        """执行一个决策周期"""
        from app.services.hub.brain import hub_brain
        from app.models.hub_log import HubLog
        
        logger.info(f"[HubDaemon] [CYCLE] Agent #{agent.id} '{agent.name}' executing cycle")
        
        # 构建分析指令
        prompt = self._build_cycle_prompt(agent)
        
        # 调用 AI
        try:
            reply = await hub_brain.chat_once(
                agent=agent,
                message=prompt,
                db=db,
                user_id=user_id,
            )
        except Exception as e:
            reply = f"[ERROR] AI 调用异常: {str(e)}"
            logger.error(f"[HubDaemon] Agent #{agent.id} AI call exception: {e}")
        
        has_error = "[ERROR]" in reply
        
        # ★ 日志穿透: 无论成功还是失败，ALL 输出都推到 hub_logs
        try:
            if has_error:
                db.add(HubLog(
                    user_id=user_id,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    log_type="error",
                    content=reply,
                ))
            else:
                # 成功的 AI 回复也推送到 War Room
                summary = reply[:300] + ("..." if len(reply) > 300 else "")
                db.add(HubLog(
                    user_id=user_id,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    log_type="ai_text",
                    content=summary,
                ))
        except Exception as log_err:
            logger.warning(f"[HubDaemon] Failed to save cycle log: {log_err}")
        
        # 更新状态
        agent.total_runs += 1
        agent.last_run_at = utc_now()
        
        if has_error:
            agent.last_error = reply[:500]
        else:
            agent.last_error = None
            # ★ 自愈机制: 成功执行 → 从 error 恢复为 active
            if agent.status == HubAgentStatus.ERROR:
                agent.status = HubAgentStatus.ACTIVE
                logger.info(f"[HubDaemon] Agent #{agent.id} auto-healed: ERROR → ACTIVE")
                try:
                    db.add(HubLog(
                        user_id=user_id,
                        agent_id=agent.id,
                        agent_name=agent.name,
                        log_type="system",
                        content=f"[✅ 自愈] {agent.name} 已从错误状态恢复正常运行",
                    ))
                except Exception:
                    pass
        
        # 检查是否产生了交易
        if any(kw in reply for kw in ["order_id", "订单已", "已下单", "已平仓"]):
            agent.total_trades += 1
        
        logger.info(
            f"[HubDaemon] Agent #{agent.id} cycle done. "
            f"Runs={agent.total_runs}, Trades={agent.total_trades}"
        )
    
    def _build_cycle_prompt(self, agent: HubAgent) -> str:
        """构建自主决策周期的 prompt (自由思考版)"""
        return (
            "轮到你值班了。看看现在市场什么情况，有没有机会，自己判断要不要动。"
        )
    
    def get_running_agents(self) -> list:
        """获取当前运行中的智能体列表"""
        return [
            key for key, task in self._agent_tasks.items()
            if not task.done()
        ]


# 全局单例
hub_daemon = HubDaemon()
