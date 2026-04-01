"""
Prompt Engine — 提示词解析与组装引擎
======================================
职责:
1. 从 PromptTemplate → 最终 system_prompt 的组装
2. 支持动态变量替换 ({balance}, {market_regime} 等)
3. 提示词格式验证
4. 市况推荐最佳模板
"""

from typing import Optional
from loguru import logger
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_template import PromptTemplate
from app.models.hub_agent import HubAgent


class PromptEngine:
    """提示词解析与组装引擎"""

    @staticmethod
    def build_prompt(
        template: Optional[PromptTemplate],
        agent: HubAgent,
        context: Optional[dict] = None,
    ) -> str:
        """
        组装完整的 Agent 专属提示词

        优先级:
        1. 如果 Agent 有绑定的 template → 使用 template.effective_prompt
        2. 否则 → 使用 Agent.system_prompt (自由文本兼容)
        """
        # 决定提示词来源
        if template:
            raw = template.effective_prompt
        else:
            raw = agent.system_prompt or ""

        if not raw:
            return ""

        # 变量替换 (安全模式: 未知变量保留原样)
        if context:
            for key, value in context.items():
                raw = raw.replace(f"{{{key}}}", str(value))

        return raw

    @staticmethod
    async def get_active_template(
        db: AsyncSession,
        agent: HubAgent,
    ) -> Optional[PromptTemplate]:
        """获取 Agent 当前激活的模板"""
        if not agent.active_template_id:
            return None

        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == agent.active_template_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def activate_template(
        db: AsyncSession,
        agent: HubAgent,
        template_id: int,
        user_id: int,
        reason: str = "手动切换",
    ):
        """
        为 Agent 激活指定模板

        1. 关闭老模板的 activation log
        2. 创建新的 activation log
        3. 更新 Agent.active_template_id
        """
        from app.models.prompt_activation_log import PromptActivationLog
        from app.core.time_utils import utc_now

        now = utc_now()

        # 关闭老的激活记录
        if agent.active_template_id:
            result = await db.execute(
                select(PromptActivationLog).where(
                    PromptActivationLog.agent_id == agent.id,
                    PromptActivationLog.template_id == agent.active_template_id,
                    PromptActivationLog.deactivated_at.is_(None),
                )
            )
            old_log = result.scalar_one_or_none()
            if old_log:
                old_log.deactivated_at = now

        # 创建新的激活记录
        new_log = PromptActivationLog(
            user_id=user_id,
            agent_id=agent.id,
            template_id=template_id,
            activated_at=now,
            reason=reason,
        )
        db.add(new_log)

        # 更新 Agent
        agent.active_template_id = template_id
        agent.updated_at = now

        logger.info(
            f"[PromptEngine] Agent #{agent.id} template changed: "
            f"{agent.active_template_id} → {template_id} ({reason})"
        )

    @staticmethod
    async def deactivate_template(
        db: AsyncSession,
        agent: HubAgent,
    ):
        """
        取消 Agent 的模板绑定 (回退到自由文本模式)
        """
        from app.models.prompt_activation_log import PromptActivationLog
        from app.core.time_utils import utc_now

        now = utc_now()

        if agent.active_template_id:
            result = await db.execute(
                select(PromptActivationLog).where(
                    PromptActivationLog.agent_id == agent.id,
                    PromptActivationLog.deactivated_at.is_(None),
                )
            )
            old_log = result.scalar_one_or_none()
            if old_log:
                old_log.deactivated_at = now

        agent.active_template_id = None
        agent.updated_at = now

    @staticmethod
    async def get_template_performance(
        db: AsyncSession,
        template_id: int,
        user_id: int,
    ) -> dict:
        """
        获取模板的收益表现

        从 positions 表聚合：
        - 总交易数、盈利数、亏损数
        - 总盈亏
        - 胜率
        """
        from app.models.position import Position, PositionStatus

        # 查询使用该模板的所有已平仓仓位
        result = await db.execute(
            select(
                func.count(Position.id),
                func.coalesce(func.sum(Position.realized_pnl), 0),
            ).where(
                Position.user_id == user_id,
                Position.prompt_template_id == template_id,
                Position.status == PositionStatus.CLOSED,
            )
        )
        row = result.one()
        total_trades = int(row[0])
        total_pnl = float(row[1])

        # 盈利交易数
        win_result = await db.execute(
            select(func.count(Position.id)).where(
                Position.user_id == user_id,
                Position.prompt_template_id == template_id,
                Position.status == PositionStatus.CLOSED,
                Position.realized_pnl > 0,
            )
        )
        win_trades = int(win_result.scalar() or 0)

        win_rate = round(win_trades / total_trades * 100, 1) if total_trades > 0 else 0.0

        return {
            "template_id": template_id,
            "total_trades": total_trades,
            "win_trades": win_trades,
            "loss_trades": total_trades - win_trades,
            "total_pnl": round(total_pnl, 4),
            "win_rate": win_rate,
        }

    @staticmethod
    async def sync_template_stats(
        db: AsyncSession,
        template_id: int,
        user_id: int,
    ):
        """将 positions 表的聚合数据同步到 prompt_template 的统计字段"""
        perf = await PromptEngine.get_template_performance(db, template_id, user_id)

        result = await db.execute(
            select(PromptTemplate).where(PromptTemplate.id == template_id)
        )
        template = result.scalar_one_or_none()
        if template:
            from decimal import Decimal
            template.total_trades = perf["total_trades"]
            template.win_trades = perf["win_trades"]
            template.total_pnl = Decimal(str(perf["total_pnl"]))

    @staticmethod
    async def recommend_template(
        db: AsyncSession,
        user_id: int,
        market_regime: str = "",
        fund_size: float = 0,
    ) -> Optional[PromptTemplate]:
        """
        根据市况和资金量推荐最佳模板

        策略:
        1. 查找匹配 market_tags 的模板
        2. 按胜率和总盈亏排序
        3. 返回表现最好的
        """
        query = (
            select(PromptTemplate)
            .where(
                PromptTemplate.user_id == user_id,
                PromptTemplate.total_trades >= 3,  # 至少 3 笔交易才有统计意义
            )
            .order_by(desc(PromptTemplate.total_pnl))
            .limit(5)
        )
        result = await db.execute(query)
        candidates = result.scalars().all()

        if not candidates:
            return None

        # 简单匹配: 如果有市况标签，优先匹配
        if market_regime:
            for c in candidates:
                tags = c.market_tags or []
                if market_regime in tags:
                    return c

        # 否则返回盈亏最好的
        return candidates[0]


# 全局单例
prompt_engine = PromptEngine()
