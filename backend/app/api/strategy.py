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
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func

from app.api.deps import CurrentUser, DbSession
from app.models.strategy import Strategy, StrategyLog, TradeMemory
from app.models.order import Order, OrderStatus
from app.models.position import Position, PositionStatus
from app.services.quant.strategy import StrategyEngine, list_templates, get_template


router = APIRouter(tags=["Strategy"])


# ==================== Schemas ====================

class StrategyCreateRequest(BaseModel):
    """创建策略请求"""
    name: str = Field(..., example="BTC RSI 超卖反弹")
    symbol: str = Field(..., example="BTCUSDT")
    interval: str = Field(default="1h", example="1h")
    config_yaml: str = Field(..., example="name: test\nsymbol: BTCUSDT\n...")
    decision_interval: str = Field(default="30m", example="30m")


class StrategyUpdateRequest(BaseModel):
    """更新策略请求"""
    name: Optional[str] = None
    symbol: Optional[str] = None
    interval: Optional[str] = None
    config_yaml: Optional[str] = None
    decision_interval: Optional[str] = None


class StrategyResponse(BaseModel):
    """策略响应"""
    id: int
    user_id: int
    name: str
    symbol: str
    interval: str
    config_yaml: str
    strategy_type: str
    is_active: bool
    decision_interval: str
    last_run_at: Optional[str] = None
    last_signal: Optional[str] = None
    total_trades: int
    win_trades: int
    total_pnl: Decimal
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True, "json_encoders": {Decimal: str}}


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
    pnl: Optional[Decimal] = None
    created_at: str

    model_config = {"from_attributes": True, "json_encoders": {Decimal: str}}


class TemplateResponse(BaseModel):
    """策略模板响应"""
    id: str
    name: str
    symbol: str
    interval: str
    config_yaml: str
    strategy_type: Optional[str] = None
    modules: Optional[str] = None


# MemoryResponse 统一使用 journal.py 的 TradeMemoryResponse
# 避免双重定义导致字段不一致
from app.api.journal import TradeMemoryResponse as MemoryResponse


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
        "strategy_type": getattr(s, "strategy_type", "basic"),
        "is_active": s.is_active,
        "decision_interval": getattr(s, "decision_interval", "30m") or "30m",
        "last_run_at": s.last_run_at.isoformat() + "Z" if s.last_run_at else None,
        "last_signal": s.last_signal,
        "total_trades": s.total_trades,
        "win_trades": s.win_trades,
        "total_pnl": str(s.total_pnl),
        "created_at": s.created_at.isoformat() + "Z" if s.created_at else "",
        "updated_at": s.updated_at.isoformat() + "Z" if s.updated_at else "",
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


class StrategyStatsResponse(BaseModel):
    """全局策略统计"""
    total_trades: int
    win_trades: int
    win_rate: float
    total_pnl: float


@router.get("/stats", response_model=StrategyStatsResponse)
async def get_strategy_stats(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取量化策略的统计（仅 source=quant 的交易）
    
    数据来源:
    - total_trades: Order 表 FILLED 且 note 含 'Strategy:' 的订单
    - total_pnl: Position 表 source=quant 已平仓位的 realized_pnl 之和
    - win_rate: realized_pnl > 0 的已平仓位占比
    """
    user_id = current_user.id
    
    # 1. 量化策略的已成交订单数
    r1 = await db.execute(
        select(func.count(Order.id)).where(
            Order.user_id == user_id,
            Order.status == OrderStatus.FILLED,
            Order.note.like("Strategy:%"),
        )
    )
    total_trades = r1.scalar() or 0
    
    # 2. source=quant 已平仓位的 realized_pnl 汇总
    r2 = await db.execute(
        select(
            func.coalesce(func.sum(Position.realized_pnl), 0),
            func.count(Position.id),
        ).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.CLOSED,
            Position.source == "quant",
        )
    )
    row = r2.one()
    total_pnl = float(row[0])
    closed_count = row[1]
    
    # 3. 盈利仓位数
    r3 = await db.execute(
        select(func.count(Position.id)).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.CLOSED,
            Position.source == "quant",
            Position.realized_pnl > 0,
        )
    )
    win_trades = r3.scalar() or 0
    
    win_rate = round((win_trades / closed_count * 100), 1) if closed_count > 0 else 0.0
    
    return StrategyStatsResponse(
        total_trades=total_trades,
        win_trades=win_trades,
        win_rate=win_rate,
        total_pnl=round(total_pnl, 2),
    )


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
    
    # decision_interval 可以在运行中修改，其他字段需停止后修改
    only_decision_interval = (
        request.decision_interval is not None
        and request.name is None
        and request.symbol is None
        and request.interval is None
        and request.config_yaml is None
    )
    
    if strategy.is_active and not only_decision_interval:
        raise HTTPException(
            status_code=400,
            detail="策略运行中，请先停止再修改（决策间隔可直接修改）",
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
    if request.decision_interval is not None:
        strategy.decision_interval = request.decision_interval
    
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
    await db.refresh(strategy)
    
    return _strategy_to_response(strategy)


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
    await db.refresh(strategy)
    
    return _strategy_to_response(strategy)


@router.post("/{strategy_id}/run-once")
async def run_strategy_once(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """手动触发一次策略决策"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    
    from app.services.agent.autopilot import autopilot
    try:
        intervals = [strategy.interval]
        reply = await autopilot._run_cycle(
            user_id=current_user.id,
            symbol=strategy.symbol,
            intervals=intervals,
            strategy_id=strategy.id,
        )
        return {
            "message": f"策略 '{strategy.name}' 已执行一次决策",
            "reply": reply,
        }
    except Exception as e:
        logger.exception(f"策略 '{strategy.name}' (#{strategy.id}) 决策执行失败")
        raise HTTPException(status_code=500, detail=f"决策执行失败: {str(e)}")


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
            "created_at": log.created_at.isoformat() + "Z" if log.created_at else "",
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
            "strategy_type": t.get("strategy_type"),
            "modules": t.get("modules"),
        })
    return result


@router.get("/{strategy_id}/memories", response_model=List[MemoryResponse])
async def get_memories(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, le=100),
):
    """获取策略相关的交易记忆（仅量化策略来源）"""
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
    
    # 获取该交易对 + 量化来源的记忆（不再混入手动交易）
    result = await db.execute(
        select(TradeMemory)
        .where(
            TradeMemory.user_id == current_user.id,
            TradeMemory.symbol == strategy.symbol,
            TradeMemory.source == "quant",
        )
        .order_by(desc(TradeMemory.created_at))
        .limit(limit)
    )
    memories = result.scalars().all()
    
    return [
        MemoryResponse(
            id=m.id,
            symbol=m.symbol,
            source=m.source,
            side=m.side,
            entry_price=m.entry_price,
            exit_price=m.exit_price,
            leverage=m.leverage,
            margin_used=m.margin_used,
            trade_result=m.trade_result,
            pnl_pct=m.pnl_pct,
            pnl_usdt=m.pnl_usdt,
            duration_minutes=m.duration_minutes,
            close_reason=m.close_reason,
            had_stop_loss=m.had_stop_loss,
            had_take_profit=m.had_take_profit,
            open_reason=m.open_reason,
            indicators_snapshot=m.indicators_snapshot,
            lesson=m.lesson,
            strategy_name=m.strategy_name,
            created_at=m.created_at.isoformat() + "Z" if m.created_at else None,
        )
        for m in memories
    ]

