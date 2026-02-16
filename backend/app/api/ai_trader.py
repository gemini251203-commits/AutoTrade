"""
AI Trader API
==============
AI 自主交易机器人的 REST API

端点:
- GET    /status               运行状态
- POST   /start                启动
- POST   /stop                 停止
- GET    /decisions             决策历史 (含思维链)
- GET    /decisions/{id}        单条决策详情
- GET    /config               获取配置
- PUT    /config               更新配置
- POST   /run-once             手动触发一次决策周期
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import CurrentUser
from app.models.ai_trader import AITraderDecision, AITraderConfig
from app.services.ai_trader import ai_trader

router = APIRouter()


# ============================================================
# Schemas
# ============================================================
class AITraderConfigSchema(BaseModel):
    enabled: bool = False
    symbols: List[str] = ["BTCUSDT", "ETHUSDT"]
    interval: str = "15m"
    max_position_pct: float = 30.0
    max_leverage: int = 20
    min_confidence: float = 0.6


class AITraderStatusResponse(BaseModel):
    running: bool
    enabled: bool
    config: Optional[AITraderConfigSchema] = None
    total_decisions: int = 0
    total_executed: int = 0
    latest_decision_at: Optional[str] = None


class DecisionSummary(BaseModel):
    id: int
    symbol: str
    cycle_no: int
    action: str
    reasoning: str
    confidence: float
    executed: bool
    order_id: Optional[int] = None
    reject_reason: Optional[str] = None
    market_snapshot: Optional[dict] = None
    account_snapshot: Optional[dict] = None
    risk_params: Optional[dict] = None
    experience_used: Optional[dict] = None
    created_at: str


# ============================================================
# 状态
# ============================================================
@router.get("/status", response_model=AITraderStatusResponse)
async def get_status(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """获取 AI Trader 运行状态"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderConfig).where(AITraderConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()

    total_result = await db.execute(
        select(func.count(AITraderDecision.id)).where(
            AITraderDecision.user_id == user_id
        )
    )
    total = total_result.scalar() or 0

    executed_result = await db.execute(
        select(func.count(AITraderDecision.id)).where(
            AITraderDecision.user_id == user_id,
            AITraderDecision.executed == True,  # noqa
        )
    )
    executed = executed_result.scalar() or 0

    latest_result = await db.execute(
        select(AITraderDecision.created_at)
        .where(AITraderDecision.user_id == user_id)
        .order_by(desc(AITraderDecision.created_at))
        .limit(1)
    )
    latest = latest_result.scalar()

    return AITraderStatusResponse(
        running=ai_trader.is_running(user_id),
        enabled=config.enabled if config else False,
        config=AITraderConfigSchema(
            enabled=config.enabled,
            symbols=config.symbols or ["BTCUSDT"],
            interval=config.interval,
            max_position_pct=config.max_position_pct,
            max_leverage=config.max_leverage,
            min_confidence=config.min_confidence,
        ) if config else None,
        total_decisions=total,
        total_executed=executed,
        latest_decision_at=latest.isoformat() if latest else None,
    )


# ============================================================
# 启动 / 停止
# ============================================================
@router.post("/start")
async def start_trader(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """启动 AI Trader"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderConfig).where(AITraderConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = AITraderConfig(user_id=user_id, enabled=True)
        db.add(config)
        await db.commit()
    else:
        config.enabled = True
        await db.commit()

    await ai_trader.start(user_id)
    return {"success": True, "message": "AI Trader 已启动"}


@router.post("/stop")
async def stop_trader(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """停止 AI Trader"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderConfig).where(AITraderConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()
    if config:
        config.enabled = False
        await db.commit()

    await ai_trader.stop(user_id)
    return {"success": True, "message": "AI Trader 已停止"}


# ============================================================
# 手动触发
# ============================================================
@router.post("/run-once")
async def run_once(
    current_user: CurrentUser,
    symbol: str = Query("BTCUSDT"),
    db: AsyncSession = Depends(get_db),
):
    """手动触发一次 AI 决策周期"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderConfig).where(AITraderConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = AITraderConfig(user_id=user_id, enabled=False)
        db.add(config)
        await db.flush()

    try:
        await ai_trader.run_cycle(db, user_id, symbol, config)
        await db.commit()
        return {"success": True, "message": f"已完成一次 {symbol} 决策周期"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 决策历史
# ============================================================
@router.get("/decisions", response_model=List[DecisionSummary])
async def get_decisions(
    current_user: CurrentUser,
    symbol: Optional[str] = None,
    action: Optional[str] = None,
    executed_only: bool = False,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取 AI 决策历史 (含完整思维链)"""
    user_id = current_user.id
    query = (
        select(AITraderDecision)
        .where(AITraderDecision.user_id == user_id)
    )

    if symbol:
        query = query.where(AITraderDecision.symbol == symbol)
    if action:
        query = query.where(AITraderDecision.action == action)
    if executed_only:
        query = query.where(AITraderDecision.executed == True)  # noqa

    query = (
        query
        .order_by(desc(AITraderDecision.created_at))
        .offset((page - 1) * size)
        .limit(size)
    )

    result = await db.execute(query)
    decisions = result.scalars().all()

    return [
        DecisionSummary(
            id=d.id,
            symbol=d.symbol,
            cycle_no=d.cycle_no,
            action=d.action,
            reasoning=d.reasoning,
            confidence=d.confidence,
            executed=d.executed,
            order_id=d.order_id,
            reject_reason=d.reject_reason,
            market_snapshot=d.market_snapshot,
            account_snapshot=d.account_snapshot,
            risk_params=d.risk_params,
            experience_used=d.experience_used,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )
        for d in decisions
    ]


@router.get("/decisions/{decision_id}")
async def get_decision_detail(
    decision_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """获取单条决策详情 (含完整思维链)"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderDecision).where(
            AITraderDecision.id == decision_id,
            AITraderDecision.user_id == user_id,
        )
    )
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="决策记录不存在")

    return {
        "id": decision.id,
        "symbol": decision.symbol,
        "cycle_no": decision.cycle_no,
        "action": decision.action,
        "reasoning": decision.reasoning,
        "confidence": decision.confidence,
        "market_snapshot": decision.market_snapshot,
        "account_snapshot": decision.account_snapshot,
        "experience_used": decision.experience_used,
        "risk_params": decision.risk_params,
        "executed": decision.executed,
        "order_id": decision.order_id,
        "reject_reason": decision.reject_reason,
        "created_at": decision.created_at.isoformat(),
    }


# ============================================================
# 配置
# ============================================================
@router.get("/config", response_model=AITraderConfigSchema)
async def get_config(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """获取 AI Trader 配置"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderConfig).where(AITraderConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return AITraderConfigSchema()

    return AITraderConfigSchema(
        enabled=config.enabled,
        symbols=config.symbols or ["BTCUSDT"],
        interval=config.interval,
        max_position_pct=config.max_position_pct,
        max_leverage=config.max_leverage,
        min_confidence=config.min_confidence,
    )


@router.put("/config", response_model=AITraderConfigSchema)
async def update_config(
    body: AITraderConfigSchema,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """更新 AI Trader 配置"""
    user_id = current_user.id

    result = await db.execute(
        select(AITraderConfig).where(AITraderConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = AITraderConfig(user_id=user_id)
        db.add(config)

    config.enabled = body.enabled
    config.symbols = body.symbols
    config.interval = body.interval
    config.max_position_pct = body.max_position_pct
    config.max_leverage = body.max_leverage
    config.min_confidence = body.min_confidence

    await db.commit()

    if not config.enabled:
        await ai_trader.stop(user_id)

    return body
