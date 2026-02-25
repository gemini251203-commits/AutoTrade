"""
Strategy API
==============
绛栫暐绠＄悊绔偣

绔偣:
    GET    /api/strategy/              - 绛栫暐鍒楄〃
    POST   /api/strategy/              - 鍒涘缓绛栫暐
    PUT    /api/strategy/{id}          - 鏇存柊绛栫暐
    DELETE /api/strategy/{id}          - 鍒犻櫎绛栫暐
    POST   /api/strategy/{id}/start    - 鍚姩鑷姩浜ゆ槗
    POST   /api/strategy/{id}/stop     - 鍋滄鑷姩浜ゆ槗
    GET    /api/strategy/{id}/logs     - 鎵ц鏃ュ織
    GET    /api/strategy/templates     - 棰勮绛栫暐妯℃澘
    GET    /api/strategy/{id}/memories - 浜ゆ槗璁板繂
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
    """鍒涘缓绛栫暐璇锋眰"""
    name: str = Field(..., example="BTC RSI 瓒呭崠鍙嶅脊")
    symbol: str = Field(..., example="BTCUSDT")
    interval: str = Field(default="1h", example="1h")
    config_yaml: str = Field(..., example="name: test\nsymbol: BTCUSDT\n...")
    decision_interval: str = Field(default="30m", example="30m")


class StrategyUpdateRequest(BaseModel):
    """鏇存柊绛栫暐璇锋眰"""
    name: Optional[str] = None
    symbol: Optional[str] = None
    interval: Optional[str] = None
    config_yaml: Optional[str] = None
    decision_interval: Optional[str] = None


class StrategyResponse(BaseModel):
    """绛栫暐鍝嶅簲"""
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
    total_pnl: float
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class StrategyLogResponse(BaseModel):
    """鎵ц鏃ュ織鍝嶅簲"""
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
    """绛栫暐妯℃澘鍝嶅簲"""
    id: str
    name: str
    symbol: str
    interval: str
    config_yaml: str
    strategy_type: Optional[str] = None
    modules: Optional[str] = None


class MemoryResponse(BaseModel):
    """浜ゆ槗璁板繂鍝嶅簲"""
    id: int
    symbol: str
    source: Optional[str] = None
    side: Optional[str] = None
    leverage: Optional[int] = None
    strategy_name: Optional[str] = None
    trade_result: str
    pnl_pct: float
    pnl_usdt: Optional[float] = None
    situation: Optional[str] = None
    lesson: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


# ==================== Helper ====================

def _strategy_to_response(s: Strategy) -> dict:
    """灏?ORM 妯″瀷杞负鍝嶅簲瀛楀吀"""
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
        "total_pnl": s.total_pnl,
        "created_at": s.created_at.isoformat() + "Z" if s.created_at else "",
        "updated_at": s.updated_at.isoformat() + "Z" if s.updated_at else "",
    }


# ==================== Routes ====================

@router.get("/", response_model=List[StrategyResponse])
async def list_strategies(
    current_user: CurrentUser,
    db: DbSession,
):
    """鑾峰彇鐢ㄦ埛鐨勭瓥鐣ュ垪琛?""
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
    鍒涘缓绛栫暐
    
    浼氶獙璇?YAML 閰嶇疆鐨勫悎娉曟€э紙鎸囨爣鍚嶇О銆佹瘮杈冭繍绠楃绛夛級
    """
    # 楠岃瘉 YAML
    engine = StrategyEngine()
    try:
        engine.parse_yaml(request.config_yaml)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"YAML 閰嶇疆鏃犳晥: {str(e)}",
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
    """鏇存柊绛栫暐閰嶇疆"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
    # decision_interval 鍙互鍦ㄨ繍琛屼腑淇敼锛屽叾浠栧瓧娈甸渶鍋滄鍚庝慨鏀?
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
            detail="绛栫暐杩愯涓紝璇峰厛鍋滄鍐嶄慨鏀癸紙鍐崇瓥闂撮殧鍙洿鎺ヤ慨鏀癸級",
        )
    
    # 濡傛灉鏇存柊浜?YAML锛岄獙璇佸悎娉曟€?
    if request.config_yaml:
        engine = StrategyEngine()
        try:
            engine.parse_yaml(request.config_yaml)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"YAML 鏃犳晥: {str(e)}")
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
    """鍒犻櫎绛栫暐"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
    if strategy.is_active:
        raise HTTPException(status_code=400, detail="绛栫暐杩愯涓紝璇峰厛鍋滄鍐嶅垹闄?)
    
    await db.delete(strategy)
    await db.commit()
    return {"message": f"绛栫暐 '{strategy.name}' 宸插垹闄?}


@router.post("/{strategy_id}/start")
async def start_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """鍚姩绛栫暐鑷姩浜ゆ槗"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
    if strategy.is_active:
        raise HTTPException(status_code=400, detail="绛栫暐宸插湪杩愯涓?)
    
    # 鍐嶆楠岃瘉 YAML
    engine = StrategyEngine()
    try:
        engine.parse_yaml(strategy.config_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"绛栫暐閰嶇疆鏃犳晥: {str(e)}")
    
    strategy.is_active = True
    await db.commit()
    
    return {"message": f"绛栫暐 '{strategy.name}' 宸插惎鍔?, "is_active": True}


@router.post("/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """鍋滄绛栫暐鑷姩浜ゆ槗"""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
    strategy.is_active = False
    await db.commit()
    
    return {"message": f"绛栫暐 '{strategy.name}' 宸插仠姝?, "is_active": False}


@router.post("/{strategy_id}/run-once")
async def run_strategy_once(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """鎵嬪姩瑙﹀彂涓€娆＄瓥鐣ュ喅绛?""
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
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
            "message": f"绛栫暐 '{strategy.name}' 宸叉墽琛屼竴娆″喅绛?,
            "reply": reply,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"鍐崇瓥鎵ц澶辫触: {str(e)}")


@router.get("/{strategy_id}/logs", response_model=List[StrategyLogResponse])
async def get_strategy_logs(
    strategy_id: int,
    current_user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=50, le=200),
):
    """鑾峰彇绛栫暐鎵ц鏃ュ織"""
    # 纭绛栫暐灞炰簬褰撳墠鐢ㄦ埛
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
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
    """鑾峰彇棰勮绛栫暐妯℃澘鍒楄〃"""
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
    """鑾峰彇绛栫暐鐩稿叧鐨勪氦鏄撹蹇嗭紙浠呴噺鍖栫瓥鐣ユ潵婧愶級"""
    # 鍏堣幏鍙栫瓥鐣ョ殑 symbol
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="绛栫暐涓嶅瓨鍦?)
    
    # 鑾峰彇璇ヤ氦鏄撳 + 閲忓寲鏉ユ簮鐨勮蹇嗭紙涓嶅啀娣峰叆鎵嬪姩浜ゆ槗锛?
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
        {
            "id": m.id,
            "symbol": m.symbol,
            "source": m.source,
            "side": m.side,
            "leverage": m.leverage,
            "strategy_name": m.strategy_name,
            "trade_result": m.trade_result,
            "pnl_pct": m.pnl_pct,
            "pnl_usdt": m.pnl_usdt,
            "situation": m.situation,
            "lesson": m.lesson,
            "created_at": m.created_at.isoformat() + "Z" if m.created_at else "",
        }
        for m in memories
    ]
