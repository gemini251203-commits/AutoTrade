"""
Strategy API
==============
策略管理端点

端点:
    GET    /api/strategy/              - 策略列表
    POST   /api/strategy/              - 创建策略
    PUT    /api/strategy/{id}          - 更新策略
    DELETE /api/strategy/{id}          - 删除策略
    POST   /api/strategy/{id}/start    - 启动自动交易
    POST   /api/strategy/{id}/stop     - 停止自动交易
    GET    /api/strategy/{id}/logs     - 执行日志
    GET    /api/strategy/templates     - 预设策略模板
    GET    /api/strategy/{id}/memories - 交易记忆
"""

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func

from app.api.deps import CurrentUser, DbSession
from app.models.strategy import Strategy, StrategyLog, TradeMemory
from app.services.quant.strategy import StrategyEngine, list_templates, get_template


router = APIRouter(tags=["Strategy"])


# ==================== Schemas ====================

class StrategyCreateRequest(BaseModel):
    """创建策略请求"""
    name: str = Field(..., example="BTC RSI 超卖反弹")
    symbol: str = Field(..., example="BTCUSDT")
    interval: str = Field(default="1h", example="1h")
    config_yaml: str = Field(..., example="name: test\nsymbol: BTCUSDT\n...")


class StrategyUpdateRequest(BaseModel):
    """更新策略请求"""
    name: Optional[str] = None
    symbol: Optional[str] = None
    interval: Optional[str] = None
    config_yaml: Optional[str] = None


class StrategyResponse(BaseModel):
    """策略响应"""
    id: int
    user_id: int
    name: str
    symbol: str
    interval: str
    config_yaml: str
    is_active: bool
    last_run_at: Optional[str] = None
    last_signal: Optional[str] = None
    total_trades: int
    win_trades: int
    total_pnl: float
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class StrategyLogResponse(BaseModel):
    """执行日志响应"""
    id: int
    strategy_id: int
    signal_type: str
    action: str
    side: Optional[str] = None
    ai_approve: Optional[bool] = None
    ai_confidence: Optional[float] = None
    ai_reason: Optional[str] = None
    risk_passed: Optional[bool] = None
    risk_reason: Optional[str] = None
    order_id: Optional[int] = None
    pnl: Optional[float] = None
    created_at: str

    class Config:
        from_attributes = True


class TemplateResponse(BaseModel):
    """策略模板响应"""
    id: str
    name: str
    symbol: str
    interval: str
    config_yaml: str


class MemoryResponse(BaseModel):
    """交易记忆响应"""
    id: int
    symbol: str
    strategy_name: Optional[str] = None
    trade_result: str
    pnl_pct: float
    situation: Optional[str] = None
    lesson: str
    created_at: str

    class Config:
        from_attributes = True


# ==================== Helper ====================

def _strategy_to_response(s: Strategy) -> dict:
    """将 ORM 模型转为响应字典"""
    return {
        "id": s.id,
        "user_id": s.user_id,
        "name": s.name,
        "symbol": s.symbol,
        "interval": s.interval,
        "config_yaml": s.config_yaml,
        "is_active": s.is_active,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_signal": s.last_signal,
        "total_trades": s.total_trades,
        "win_trades": s.win_trades,
        "total_pnl": s.total_pnl,
        "created_at": s.created_at.isoformat() if s.created_at else "",
        "updated_at": s.updated_at.isoformat() if s.updated_at else "",
    }


# ==================== Routes ====================

@router.get("/", response_model=List[StrategyResponse])
async def list_strategies(
    current_user: CurrentUser,
    db: DbSession,
):
    """获取用户的策略列表"""
    result = await db.execute(
        select(Strategy)
        .where(Strategy.user_id == current_user.id)
        .order_by(desc(Strategy.updated_at))
    )
    strategies = result.scalars().all()
    return [_strategy_to_response(s) for s in strategies]


@router.post("/", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    request: StrategyCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    创建策略
    
    会验证 YAML 配置的合法性（指标名称、比较运算符等）
    """
    # 验证 YAML
    engine = StrategyEngine()
    try:
        engine.parse_yaml(request.config_yaml)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"YAML 配置无效: {str(e)}",
        )
    
    strategy = Strategy(
        user_id=current_user.id,
        name=request.name,
        symbol=request.symbol,
        interval=request.interval,
        config_yaml=request.config_yaml,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    
    return _strategy_to_response(strategy)


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    request: StrategyUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """更新策略配置"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    if strategy.is_active:
        raise HTTPException(
            status_code=400,
            detail="策略运行中，请先停止再修改",
        )
    
    # 如果更新了 YAML，验证合法性
    if request.config_yaml:
        engine = StrategyEngine()
        try:
            engine.parse_yaml(request.config_yaml)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"YAML 无效: {str(e)}")
        strategy.config_yaml = request.config_yaml
    
    if request.name is not None:
        strategy.name = request.name
    if request.symbol is not None:
        strategy.symbol = request.symbol
    if request.interval is not None:
        strategy.interval = request.interval
    
    await db.commit()
    await db.refresh(strategy)
    return _strategy_to_response(strategy)


@router.delete("/{strategy_id}")
async def delete_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """删除策略"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    if strategy.is_active:
        raise HTTPException(status_code=400, detail="策略运行中，请先停止再删除")
    
    await db.delete(strategy)
    await db.commit()
    return {"message": f"策略 '{strategy.name}' 已删除"}


@router.post("/{strategy_id}/start")
async def start_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """启动策略自动交易"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    if strategy.is_active:
        raise HTTPException(status_code=400, detail="策略已在运行中")
    
    # 再次验证 YAML
    engine = StrategyEngine()
    try:
        engine.parse_yaml(strategy.config_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"策略配置无效: {str(e)}")
    
    strategy.is_active = True
    await db.commit()
    
    return {"message": f"策略 '{strategy.name}' 已启动", "is_active": True}


@router.post("/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """停止策略自动交易"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    strategy.is_active = False
    await db.commit()
    
    return {"message": f"策略 '{strategy.name}' 已停止", "is_active": False}


@router.get("/{strategy_id}/logs", response_model=List[StrategyLogResponse])
async def get_strategy_logs(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=50, le=200),
):
    """获取策略执行日志"""
    # 确认策略属于当前用户
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="策略不存在")
    
    result = await db.execute(
        select(StrategyLog)
        .where(StrategyLog.strategy_id == strategy_id)
        .order_by(desc(StrategyLog.created_at))
        .limit(limit)
    )
    logs = result.scalars().all()
    
    return [
        {
            "id": log.id,
            "strategy_id": log.strategy_id,
            "signal_type": log.signal_type,
            "action": log.action,
            "side": log.side,
            "ai_approve": log.ai_approve,
            "ai_confidence": log.ai_confidence,
            "ai_reason": log.ai_reason,
            "risk_passed": log.risk_passed,
            "risk_reason": log.risk_reason,
            "order_id": log.order_id,
            "pnl": log.pnl,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in logs
    ]


@router.get("/templates", response_model=List[TemplateResponse])
async def get_templates():
    """获取预设策略模板列表"""
    templates = list_templates()
    result = []
    for t in templates:
        yaml_content = get_template(t["id"])
        result.append({
            "id": t["id"],
            "name": t["name"],
            "symbol": t["symbol"],
            "interval": t["interval"],
            "config_yaml": yaml_content.strip() if yaml_content else "",
        })
    return result


@router.get("/{strategy_id}/memories", response_model=List[MemoryResponse])
async def get_memories(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, le=100),
):
    """获取策略相关的交易记忆"""
    # 先获取策略的 symbol
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    # 获取该交易对的记忆
    result = await db.execute(
        select(TradeMemory)
        .where(
            TradeMemory.user_id == current_user.id,
            TradeMemory.symbol == strategy.symbol,
        )
        .order_by(desc(TradeMemory.created_at))
        .limit(limit)
    )
    memories = result.scalars().all()
    
    return [
        {
            "id": m.id,
            "symbol": m.symbol,
            "strategy_name": m.strategy_name,
            "trade_result": m.trade_result,
            "pnl_pct": m.pnl_pct,
            "situation": m.situation,
            "lesson": m.lesson,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in memories
    ]
