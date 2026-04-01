"""
Prompt Template API
====================
提示词模板管理 API

路由前缀: /api/prompts
端点:
  GET    /templates               → 模板列表
  POST   /templates               → 创建模板
  PUT    /templates/{id}          → 更新模板
  DELETE /templates/{id}          → 删除模板
  POST   /templates/{id}/activate → 激活到指定 Agent
  POST   /templates/{id}/deactivate → 取消绑定
  GET    /templates/{id}/performance → 收益分析
  POST   /templates/{id}/duplicate   → 复制模板
  GET    /recommend               → 市况推荐
  GET    /presets                  → 预置模板列表
  POST   /presets/{id}/import     → 导入预置模板
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, desc

from app.api.deps import CurrentUser, DbSession
from app.models.prompt_template import PromptTemplate
from app.core.time_utils import utc_now

router = APIRouter(tags=["Prompts"])


# ============================================================
# Pydantic Schemas
# ============================================================

class PromptTemplateCreateRequest(BaseModel):
    """创建模板"""
    name: str
    description: Optional[str] = None
    strategy_prompt: str = ""
    risk_rules: str = ""
    behavior_directives: str = ""
    raw_prompt: str = ""
    is_structured: bool = False
    market_tags: Optional[List[str]] = None
    parent_id: Optional[int] = None


class PromptTemplateUpdateRequest(BaseModel):
    """更新模板"""
    name: Optional[str] = None
    description: Optional[str] = None
    strategy_prompt: Optional[str] = None
    risk_rules: Optional[str] = None
    behavior_directives: Optional[str] = None
    raw_prompt: Optional[str] = None
    is_structured: Optional[bool] = None
    market_tags: Optional[List[str]] = None


class PromptTemplateResponse(BaseModel):
    """模板响应"""
    id: int
    name: str
    version: int
    description: Optional[str]
    strategy_prompt: str
    risk_rules: str
    behavior_directives: str
    raw_prompt: str
    is_structured: bool
    market_tags: Optional[List[str]]
    parent_id: Optional[int]
    is_preset: bool
    total_trades: int
    win_trades: int
    total_pnl: float
    win_rate: float
    active_hours: float
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class ActivateRequest(BaseModel):
    """激活模板到 Agent"""
    agent_id: int
    reason: Optional[str] = "手动切换"


class DeactivateRequest(BaseModel):
    """取消模板绑定"""
    agent_id: int


# ============================================================
# Helpers
# ============================================================

def _template_to_response(t: PromptTemplate) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=t.id,
        name=t.name,
        version=t.version,
        description=t.description,
        strategy_prompt=t.strategy_prompt,
        risk_rules=t.risk_rules,
        behavior_directives=t.behavior_directives,
        raw_prompt=t.raw_prompt,
        is_structured=t.is_structured,
        market_tags=t.market_tags,
        parent_id=t.parent_id,
        is_preset=t.is_preset,
        total_trades=t.total_trades,
        win_trades=t.win_trades,
        total_pnl=float(t.total_pnl),
        win_rate=t.win_rate,
        active_hours=t.active_hours,
        created_at=t.created_at.isoformat() if t.created_at else "",
        updated_at=t.updated_at.isoformat() if t.updated_at else "",
    )


# ============================================================
# 路由: CRUD
# ============================================================

@router.get("/templates")
async def list_templates(
    current_user: CurrentUser,
    db: DbSession,
    include_presets: bool = True,
):
    """列出用户的所有模板 (含预置模板)"""
    from sqlalchemy import or_

    filters = [PromptTemplate.user_id == current_user.id]
    if include_presets:
        # 预置模板 user_id=0 或 is_preset=True
        filters = [
            or_(
                PromptTemplate.user_id == current_user.id,
                PromptTemplate.is_preset == True,
            )
        ]

    result = await db.execute(
        select(PromptTemplate)
        .where(*filters)
        .order_by(desc(PromptTemplate.updated_at))
    )
    templates = result.scalars().all()

    return {
        "templates": [_template_to_response(t) for t in templates],
        "total": len(templates),
    }


@router.post("/templates", status_code=201)
async def create_template(
    body: PromptTemplateCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """创建新模板"""
    # 计算版本号: 同名模板自增
    from sqlalchemy import func
    ver_result = await db.execute(
        select(func.coalesce(func.max(PromptTemplate.version), 0)).where(
            PromptTemplate.user_id == current_user.id,
            PromptTemplate.name == body.name,
        )
    )
    next_version = int(ver_result.scalar() or 0) + 1

    template = PromptTemplate(
        user_id=current_user.id,
        name=body.name,
        version=next_version,
        description=body.description,
        strategy_prompt=body.strategy_prompt,
        risk_rules=body.risk_rules,
        behavior_directives=body.behavior_directives,
        raw_prompt=body.raw_prompt,
        is_structured=body.is_structured,
        market_tags=body.market_tags,
        parent_id=body.parent_id,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)

    return _template_to_response(template)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    body: PromptTemplateUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """更新模板"""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.id == template_id,
            PromptTemplate.user_id == current_user.id,
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(template, field):
            setattr(template, field, value)

    template.updated_at = utc_now()
    await db.commit()
    await db.refresh(template)

    return _template_to_response(template)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """删除模板"""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.id == template_id,
            PromptTemplate.user_id == current_user.id,
            PromptTemplate.is_preset == False,  # 预置模板不可删除
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在或无法删除")

    await db.delete(template)
    await db.commit()
    return {"success": True}


# ============================================================
# 路由: 模板激活/绑定
# ============================================================

@router.post("/templates/{template_id}/activate")
async def activate_template(
    template_id: int,
    body: ActivateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """将模板激活到指定 Agent"""
    from app.services.hub.prompt_engine import prompt_engine
    from app.models.hub_agent import HubAgent

    # 验证模板存在
    t_result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    template = t_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    # 验证 Agent 存在
    a_result = await db.execute(
        select(HubAgent).where(
            HubAgent.id == body.agent_id,
            HubAgent.user_id == current_user.id,
        )
    )
    agent = a_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")

    # 同步模板内容到 agent.system_prompt (确保兼容)
    agent.system_prompt = template.effective_prompt

    await prompt_engine.activate_template(
        db=db,
        agent=agent,
        template_id=template_id,
        user_id=current_user.id,
        reason=body.reason or "手动切换",
    )

    await db.commit()
    return {
        "success": True,
        "agent_id": body.agent_id,
        "template_id": template_id,
        "template_name": template.name,
        "message": f"已将模板 '{template.name} v{template.version}' 激活到 Agent",
    }


@router.post("/templates/{template_id}/deactivate")
async def deactivate_template(
    template_id: int,
    body: DeactivateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """取消 Agent 的模板绑定"""
    from app.services.hub.prompt_engine import prompt_engine
    from app.models.hub_agent import HubAgent

    a_result = await db.execute(
        select(HubAgent).where(
            HubAgent.id == body.agent_id,
            HubAgent.user_id == current_user.id,
        )
    )
    agent = a_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")

    await prompt_engine.deactivate_template(db, agent)
    await db.commit()
    return {"success": True, "message": "已取消模板绑定，回退到自由文本模式"}


# ============================================================
# 路由: 收益分析
# ============================================================

@router.get("/templates/{template_id}/performance")
async def get_template_performance(
    template_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """获取模板的收益表现"""
    from app.services.hub.prompt_engine import prompt_engine

    perf = await prompt_engine.get_template_performance(
        db, template_id, current_user.id,
    )
    return perf


# ============================================================
# 路由: 复制模板
# ============================================================

@router.post("/templates/{template_id}/duplicate")
async def duplicate_template(
    template_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """复制一个模板 (用于从预置模板创建自己的副本)"""
    result = await db.execute(
        select(PromptTemplate).where(PromptTemplate.id == template_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="模板不存在")

    new_template = PromptTemplate(
        user_id=current_user.id,
        name=f"{source.name} (副本)",
        version=1,
        description=source.description,
        strategy_prompt=source.strategy_prompt,
        risk_rules=source.risk_rules,
        behavior_directives=source.behavior_directives,
        raw_prompt=source.raw_prompt,
        is_structured=source.is_structured,
        market_tags=source.market_tags,
        parent_id=source.id,
        is_preset=False,
    )
    db.add(new_template)
    await db.commit()
    await db.refresh(new_template)

    return _template_to_response(new_template)


# ============================================================
# 路由: 市况推荐
# ============================================================

@router.get("/recommend")
async def recommend_template(
    current_user: CurrentUser,
    db: DbSession,
    market_regime: str = "",
    fund_size: float = 0,
):
    """根据市况和资金量推荐最佳模板"""
    from app.services.hub.prompt_engine import prompt_engine

    template = await prompt_engine.recommend_template(
        db, current_user.id, market_regime, fund_size,
    )
    if not template:
        return {"recommendation": None, "message": "暂无足够数据进行推荐"}

    return {
        "recommendation": _template_to_response(template),
        "message": f"推荐 '{template.name}' (胜率 {template.win_rate}%)",
    }


# ============================================================
# 路由: 预置模板
# ============================================================

@router.get("/presets")
async def list_presets(
    db: DbSession,
):
    """列出所有预置模板"""
    result = await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.is_preset == True)
        .order_by(PromptTemplate.id)
    )
    templates = result.scalars().all()
    return {
        "presets": [_template_to_response(t) for t in templates],
        "total": len(templates),
    }


@router.post("/presets/seed")
async def seed_presets(
    current_user: CurrentUser,
    db: DbSession,
):
    """初始化预置模板 (仅当不存在时创建)"""
    count = await _seed_preset_templates(db)
    return {"success": True, "created": count}


# ============================================================
# 预置模板数据
# ============================================================

PRESET_TEMPLATES = [
    {
        "name": "保守防守",
        "description": "只做高确定性交易，严格止损，适合所有市况和资金量",
        "is_structured": True,
        "strategy_prompt": (
            "【身份定义】\n"
            "你是一个极度保守的交易员。你的首要目标是保住本金，盈利是次要的。\n"
            "你宁可错过 10 次机会，也不愿亏损 1 次。\n\n"
            "【交易策略 - 核心规则】\n"
            "1. 趋势判断：只在多个时间周期(15m/1h/4h)方向一致时才考虑入场\n"
            "2. 入场条件：RSI 回到 30-40(做多) 或 60-70(做空) 区间 + 明确的支撑/阻力确认\n"
            "3. 仓位管理：单笔投入不超过账户余额的 10%\n"
            "4. 止损必设：开仓时立即设定止损，距离入场价不超过 2%\n"
            "5. 止盈策略：盈利达到止损距离的 2 倍时止盈一半，剩余移动止损"
        ),
        "risk_rules": (
            "【风控规则 - 最高优先级】\n"
            "- 禁止追涨杀跌，必须等回调入场\n"
            "- 禁止同时持有超过 2 个仓位\n"
            "- 当日亏损超过 3% 时，当日停止交易\n"
            "- 杠杆上限 5 倍\n"
            "- 市场剧烈波动时(1小时涨跌超过3%)，不开新仓\n"
            "- 不做山寨币，只做 BTC 和 ETH"
        ),
        "market_tags": ["trending_up", "trending_down", "sideways", "small_fund", "medium_fund", "large_fund"],
    },
    {
        "name": "趋势追踪",
        "description": "顺势操作，金字塔加仓，适合明确趋势行情",
        "is_structured": True,
        "strategy_prompt": (
            "【身份定义】\n"
            "你是一个趋势交易员。你的核心信念是\"趋势是你的朋友\"。\n"
            "你从不预测顶底，只跟随已确认的趋势。\n\n"
            "【交易策略 - 核心规则】\n"
            "1. 趋势判断：使用 4h 级别 EMA20/EMA50 交叉确认趋势方向\n"
            "2. 入场条件：趋势确认后，等价格回踩 EMA20 时入场\n"
            "3. 加仓策略：盈利超过 3% 时，在回调不破前低/前高时加仓(金字塔)\n"
            "4. 仓位管理：初始仓位 15%，每次加仓递减(10%→5%)\n"
            "5. 出场条件：价格跌破 EMA50 或 RSI 出现顶底背离时平仓"
        ),
        "risk_rules": (
            "【风控规则 - 最高优先级】\n"
            "- 禁止逆势操作(上升趋势不做空，下降趋势不做多)\n"
            "- 单笔止损不超过 3%\n"
            "- 总仓位不超过账户的 40%\n"
            "- 杠杆 10-15 倍\n"
            "- 横盘震荡时不开新仓，等待方向确认"
        ),
        "market_tags": ["trending_up", "trending_down", "medium_fund", "large_fund"],
    },
    {
        "name": "震荡网格",
        "description": "识别区间，开网格自动交易，适合横盘震荡行情",
        "is_structured": True,
        "strategy_prompt": (
            "【身份定义】\n"
            "你是一个网格交易专家。你擅长在价格区间内反复套利。\n"
            "你不预测方向，只利用波动赚取价差。\n\n"
            "【交易策略 - 核心规则】\n"
            "1. 区间判断：用 1h 布林带识别当前区间(上轨=阻力，下轨=支撑)\n"
            "2. 网格参数：区间高低 5-8% 范围，10-15 格\n"
            "3. 适用币种：BTC、ETH(优先)，SOL(可选)\n"
            "4. 持仓管理：同时最多运行 2 个网格\n"
            "5. 退出条件：价格突破区间上下沿 2% 时关闭网格"
        ),
        "risk_rules": (
            "【风控规则 - 最高优先级】\n"
            "- 网格杠杆 10-20 倍\n"
            "- 单个网格投入不超过账户的 30%\n"
            "- 如果检测到明确趋势(EMA20/50 交叉)，立即关闭网格\n"
            "- 禁止在剧烈波动(1h涨跌>5%)时开网格"
        ),
        "market_tags": ["sideways", "medium_fund", "large_fund"],
    },
    {
        "name": "激进突破",
        "description": "追涨突破，高杠杆短持，适合剧烈波动行情",
        "is_structured": True,
        "strategy_prompt": (
            "【身份定义】\n"
            "你是一个突破交易员。你专注于捕捉价格突破关键位后的快速行情。\n"
            "你的交易风格是快进快出，持仓时间通常不超过 4 小时。\n\n"
            "【交易策略 - 核心规则】\n"
            "1. 关键位识别：前高/前低、整数关口、布林带突破\n"
            "2. 入场条件：放量突破关键位 + 回踩确认不破\n"
            "3. 仓位管理：单笔投入 20%，高杠杆(15-20倍)\n"
            "4. 止盈策略：快速止盈，盈利 2-3% 即可平仓\n"
            "5. 止损策略：突破失败(回到关键位以下)立即止损"
        ),
        "risk_rules": (
            "【风控规则 - 最高优先级】\n"
            "- 每日最多 3 笔交易\n"
            "- 止损距离不超过 1.5%\n"
            "- 连续亏损 2 笔后当日停止交易\n"
            "- 不在低波动环境下交易(ATR 过低时观望)"
        ),
        "market_tags": ["high_volatility", "medium_fund", "large_fund"],
    },
    {
        "name": "冷静观察",
        "description": "以观察和报告为主，极少交易，适合不确定行情和小资金",
        "is_structured": True,
        "strategy_prompt": (
            "【身份定义】\n"
            "你是一个谨慎的市场观察者。你的主要工作是分析市场并提供报告。\n"
            "除非出现极高确定性的机会，否则你不交易。\n\n"
            "【交易策略 - 核心规则】\n"
            "1. 分析优先：每次值班重点是分析市场状况，写出清晰的行情报告\n"
            "2. 入场标准极高：至少 3 个独立信号同时确认才考虑入场\n"
            "   - 技术面(趋势+指标) + 资金面(资金费率) + 情绪面(市场情绪)\n"
            "3. 仓位极小：单笔不超过账户的 5%\n"
            "4. 杠杆极低：最高 3 倍"
        ),
        "risk_rules": (
            "【风控规则 - 最高优先级】\n"
            "- 每周最多 2 笔交易\n"
            "- 禁止使用超过 3 倍杠杆\n"
            "- 持仓总值不超过账户的 10%\n"
            "- 任何不确定的情况下，选择观望"
        ),
        "market_tags": ["sideways", "high_volatility", "small_fund"],
    },
    {
        "name": "事件驱动",
        "description": "基于新闻情绪和技术确认交易，适合新闻驱动型行情",
        "is_structured": True,
        "strategy_prompt": (
            "【身份定义】\n"
            "你是一个事件驱动型交易员。你密切关注市场新闻和情绪变化。\n"
            "你的优势是快速解读事件对价格的影响并做出反应。\n\n"
            "【交易策略 - 核心规则】\n"
            "1. 情报收集：利用 get_market_sentiment 等工具监控市场情绪\n"
            "2. 事件分类：\n"
            "   - 利多(降息/ETF通过/合规利好) → 寻找做多机会\n"
            "   - 利空(监管/黑客/暴雷) → 寻找做空机会或避险\n"
            "3. 入场时机：事件发生后等技术面确认(不追第一波)\n"
            "4. 仓位管理：根据事件影响力决定仓位大小(重大事件 20%，一般事件 10%)"
        ),
        "risk_rules": (
            "【风控规则 - 最高优先级】\n"
            "- 重大事件发布前 30 分钟不开新仓\n"
            "- 事件交易止损放宽到 3%(波动较大)\n"
            "- 已有仓位在重大事件前减仓 50%\n"
            "- 情绪极端(贪婪指数>80 或 <20)时反向思考"
        ),
        "market_tags": ["trending_up", "trending_down", "high_volatility", "medium_fund", "large_fund"],
    },
]


async def _seed_preset_templates(db) -> int:
    """初始化预置模板 (仅在不存在时创建)"""
    from sqlalchemy import func

    # 检查是否已存在预置模板
    count_result = await db.execute(
        select(func.count(PromptTemplate.id)).where(
            PromptTemplate.is_preset == True,
        )
    )
    existing = int(count_result.scalar() or 0)
    if existing > 0:
        return 0

    created = 0
    for preset in PRESET_TEMPLATES:
        template = PromptTemplate(
            user_id=0,  # 系统级预置模板
            name=preset["name"],
            description=preset.get("description", ""),
            strategy_prompt=preset.get("strategy_prompt", ""),
            risk_rules=preset.get("risk_rules", ""),
            behavior_directives=preset.get("behavior_directives", ""),
            raw_prompt="",
            is_structured=preset.get("is_structured", True),
            market_tags=preset.get("market_tags"),
            is_preset=True,
            version=1,
        )
        db.add(template)
        created += 1

    await db.commit()
    return created

