"""
Pipeline API
==============
鍥涘眰娴佹按绾跨鐞嗙鐐?

绔偣:
    GET  /api/pipeline/status   - 鑾峰彇 Pipeline 瀹炴椂鐘舵€?
    GET  /api/pipeline/config   - 鑾峰彇褰撳墠閰嶇疆
    POST /api/pipeline/circuit-breaker - 鐔旀柇鎺у埗
"""

from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession, CurrentUser

router = APIRouter(tags=["Pipeline"])


# ==================== Schemas ====================

class LayerStatus(BaseModel):
    """鍗曞眰鐘舵€?""
    name: str
    status: str        # "active" | "idle" | "error" | "disabled"
    detail: str = ""
    count: int = 0     # 澶勭悊娆℃暟


class PipelineStatusResponse(BaseModel):
    """Pipeline 鏁翠綋鐘舵€?""
    is_active: bool
    circuit_breaker: bool           # 鏄惁鐔旀柇
    risk_bypass: bool = False       # 椋庢帶鏄惁宸插叧闂?
    uptime_seconds: float
    layers: List[LayerStatus]       # 鍥涘眰鐘舵€?
    stats: Dict                     # 娴佹按绾跨粺璁?
    recent_insights: List[Dict]     # 鏈€杩戜俊鍙?
    recent_verdicts: List[Dict]     # 鏈€杩戦鎺у喅绛?


class PipelineConfigResponse(BaseModel):
    """Pipeline 閰嶇疆"""
    portfolio_model: str            # "fixed_percent" | "kelly"
    risk_percent: float             # 浠撲綅鐧惧垎姣?
    default_leverage: int
    max_positions: int
    max_leverage: int
    max_daily_loss_pct: float
    max_total_exposure_pct: float
    blacklist: List[str]


class PipelineConfigUpdate(BaseModel):
    """鏇存柊 Pipeline 閰嶇疆"""
    portfolio_model: Optional[str] = None
    risk_percent: Optional[float] = None
    default_leverage: Optional[int] = None
    max_positions: Optional[int] = None
    max_leverage: Optional[int] = None
    max_daily_loss_pct: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    blacklist: Optional[List[str]] = None


class CircuitBreakerRequest(BaseModel):
    """鐔旀柇鎺у埗"""
    action: str                     # "trigger" | "reset"
    reason: str = ""


class CircuitBreakerResponse(BaseModel):
    circuit_breaker: bool
    message: str


class RiskBypassRequest(BaseModel):
    """椋庢帶寮€鍏?""
    enabled: bool                   # True=鍏抽棴椋庢帶, False=鎭㈠椋庢帶


class RiskBypassResponse(BaseModel):
    risk_bypass: bool
    message: str


# ==================== Helper: 鑾峰彇鐪熷疄 Pipeline 瀹炰緥 ====================

_startup_time = datetime.utcnow()
_recent_insights: list = []
_recent_verdicts: list = []


def _get_pipeline():
    """鑾峰彇鍏ㄥ眬 TradingPipeline 瀹炰緥 (鏉ヨ嚜 core/pipeline.py)"""
    try:
        from app.core.pipeline import get_pipeline
        return get_pipeline()
    except Exception:
        return None


def _get_risk_model():
    """鑾峰彇褰撳墠 Pipeline 涓殑 RiskModel"""
    pipeline = _get_pipeline()
    return pipeline._risk if pipeline else None


def record_insight(data: dict):
    """璁板綍鏈€杩戠殑 Insight (渚?EventBus 鍥炶皟浣跨敤)"""
    global _recent_insights
    _recent_insights.append({
        **data,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    if len(_recent_insights) > 50:
        _recent_insights = _recent_insights[-50:]


def record_verdict(data: dict):
    """璁板綍鏈€杩戠殑椋庢帶鍐崇瓥"""
    global _recent_verdicts
    _recent_verdicts.append({
        **data,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    if len(_recent_verdicts) > 50:
        _recent_verdicts = _recent_verdicts[-50:]


# ==================== Routes ====================

@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    db: DbSession,
    current_user: CurrentUser,
):
    """
    鑾峰彇 Pipeline 瀹炴椂鐘舵€?

    娣峰悎鏁版嵁婧?
    - DB 鏌ヨ: 绛栫暐鏁般€佽鍗曟暟銆佷粨浣嶆暟 (鎸佷箙鍖? 涓嶉殢閲嶅惎涓㈠け)
    - 鍐呭瓨缁熻: 鏈杩愯鏈熼棿鐨勬祦姘寸嚎璁℃暟 (杈呭姪)
    """
    from sqlalchemy import select, func
    from app.models.order import Order, OrderStatus
    from app.models.position import Position, PositionStatus
    from app.models.strategy import Strategy

    pipeline = _get_pipeline()
    risk_model = _get_risk_model()

    # 璁＄畻杩愯鏃堕棿
    uptime = (datetime.utcnow() - _startup_time).total_seconds()

    # 浠?Pipeline 鑾峰彇鍐呭瓨缁熻 (鏈杩愯)
    mem_stats = {}
    if pipeline:
        mem_stats = pipeline.get_stats()

    # ===== 浠?DB 鑾峰彇鐪熷疄鎸佷箙鍖栫粺璁?=====
    user_id = current_user.id

    # Alpha: 娲昏穬绛栫暐鏁?
    strategy_count = 0
    try:
        r = await db.execute(
            select(func.count(Strategy.id)).where(
                Strategy.user_id == user_id,
                Strategy.is_active == True,
            )
        )
        strategy_count = r.scalar() or 0
    except Exception:
        pass

    # Portfolio/Risk/Execution: 璁㈠崟缁熻
    total_orders = 0
    filled_orders = 0
    rejected_orders = 0
    try:
        r = await db.execute(
            select(func.count(Order.id)).where(Order.user_id == user_id)
        )
        total_orders = r.scalar() or 0
        r2 = await db.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user_id,
                Order.status == OrderStatus.FILLED,
            )
        )
        filled_orders = r2.scalar() or 0
        r3 = await db.execute(
            select(func.count(Order.id)).where(
                Order.user_id == user_id,
                Order.status == OrderStatus.REJECTED,
            )
        )
        rejected_orders = r3.scalar() or 0
    except Exception:
        pass

    # 浠撲綅缁熻
    open_positions = 0
    closed_positions = 0
    try:
        r = await db.execute(
            select(func.count(Position.id)).where(
                Position.user_id == user_id,
                Position.status == PositionStatus.OPEN,
            )
        )
        open_positions = r.scalar() or 0
        r2 = await db.execute(
            select(func.count(Position.id)).where(
                Position.user_id == user_id,
                Position.status == PositionStatus.CLOSED,
            )
        )
        closed_positions = r2.scalar() or 0
    except Exception:
        pass

    # 鍚堝苟缁熻
    alpha_count = strategy_count + mem_stats.get("insights_generated", 0)
    portfolio_count = total_orders  # 姣忎釜璁㈠崟閮界粡杩?Portfolio 璁＄畻
    risk_count = filled_orders + rejected_orders + mem_stats.get("risk_approved", 0) + mem_stats.get("risk_rejected", 0)
    exec_count = filled_orders + mem_stats.get("orders_executed", 0)

    is_active = total_orders > 0 or strategy_count > 0

    # 鐔旀柇 / 椋庢帶鏃佽矾鐘舵€?
    circuit_breaker = False
    risk_bypass = False
    if risk_model:
        circuit_breaker = risk_model.is_circuit_breaker_active
        risk_bypass = risk_model.risk_bypass

    # 鏋勯€犲洓灞傜姸鎬?
    layers = []

    # Alpha 灞?
    alpha_detail = f"{strategy_count} 涓椿璺冪瓥鐣?
    if pipeline and pipeline._alphas:
        alpha_names = [a.get_name() for a in pipeline._alphas]
        alpha_detail += f" 路 Models: {', '.join(alpha_names)}"
    layers.append(LayerStatus(
        name="Alpha",
        status="active" if strategy_count > 0 else "idle",
        detail=alpha_detail,
        count=alpha_count,
    ))

    # Portfolio 灞?
    portfolio_model = pipeline._portfolio if pipeline else None
    portfolio_type = type(portfolio_model).__name__ if portfolio_model else "FixedPercentModel"
    layers.append(LayerStatus(
        name="Portfolio",
        status="active" if is_active else "idle",
        detail=f"Model: {portfolio_type} 路 {total_orders} 绗旇鍗?,
        count=portfolio_count,
    ))

    # Risk 灞?
    risk_status = "active"
    if circuit_breaker:
        risk_status = "error"
    elif risk_bypass:
        risk_status = "disabled"
    elif not is_active:
        risk_status = "idle"
    
    risk_detail = f"閫氳繃: {filled_orders}, 鎷掔粷: {rejected_orders}"
    if circuit_breaker:
        risk_detail += " 鈿狅笍 鐔旀柇涓?
    elif risk_bypass:
        risk_detail += " 鈿狅笍 椋庢帶宸插叧闂?
    
    layers.append(LayerStatus(
        name="Risk",
        status=risk_status,
        detail=risk_detail,
        count=risk_count,
    ))

    # Execution 灞?
    layers.append(LayerStatus(
        name="Execution",
        status="active" if exec_count > 0 else "idle",
        detail=f"宸叉墽琛? {filled_orders} 路 鎸佷粨: {open_positions} 路 宸插钩: {closed_positions}",
        count=exec_count,
    ))

    combined_stats = {
        **mem_stats,
        "db_strategies_active": strategy_count,
        "db_total_orders": total_orders,
        "db_filled_orders": filled_orders,
        "db_rejected_orders": rejected_orders,
        "db_open_positions": open_positions,
        "db_closed_positions": closed_positions,
    }

    return PipelineStatusResponse(
        is_active=is_active,
        circuit_breaker=circuit_breaker,
        risk_bypass=risk_bypass,
        uptime_seconds=uptime,
        layers=layers,
        stats=combined_stats,
        recent_insights=list(reversed(_recent_insights[-20:])),
        recent_verdicts=list(reversed(_recent_verdicts[-20:])),
    )


@router.get("/config", response_model=PipelineConfigResponse)
async def get_pipeline_config(
    current_user: CurrentUser,
):
    """鑾峰彇褰撳墠 Pipeline 閰嶇疆 (浠庣湡瀹炲疄渚嬭鍙?"""
    pipeline = _get_pipeline()
    portfolio_model = pipeline._portfolio if pipeline else None
    risk_model = _get_risk_model()

    # 榛樿鍊?
    config = PipelineConfigResponse(
        portfolio_model="fixed_percent",
        risk_percent=10.0,
        default_leverage=5,
        max_positions=5,
        max_leverage=20,
        max_daily_loss_pct=10.0,
        max_total_exposure_pct=200.0,
        blacklist=[],
    )

    # 浠庡疄闄呮ā鍨嬭鍙?
    if portfolio_model:
        from app.services.portfolio.model import FixedPercentModel, KellyPortfolioModel
        if isinstance(portfolio_model, FixedPercentModel):
            config.portfolio_model = "fixed_percent"
            config.risk_percent = portfolio_model._risk_percent
            config.default_leverage = portfolio_model._default_leverage
            config.max_positions = portfolio_model._max_positions
        elif isinstance(portfolio_model, KellyPortfolioModel):
            config.portfolio_model = "kelly"
            config.default_leverage = portfolio_model._default_leverage
            config.max_positions = portfolio_model._max_positions

    if risk_model:
        config.max_leverage = risk_model._config.max_leverage
        config.max_daily_loss_pct = risk_model._config.max_daily_loss_pct
        config.max_total_exposure_pct = risk_model._config.max_total_exposure_pct
        config.blacklist = risk_model._config.blacklist

    return config


@router.post("/circuit-breaker", response_model=CircuitBreakerResponse)
async def control_circuit_breaker(
    current_user: CurrentUser,
    body: CircuitBreakerRequest,
):
    """
    鎺у埗椋庢帶鐔旀柇鍣?

    - trigger: 瑙﹀彂鐔旀柇 (鍋滄涓€鍒囦氦鏄?
    - reset: 瑙ｉ櫎鐔旀柇
    """
    risk_model = _get_risk_model()

    if not risk_model:
        from app.services.risk.risk_model import RiskModel
        risk_model = RiskModel()

    if body.action == "trigger":
        risk_model.trigger_circuit_breaker(body.reason)
        return CircuitBreakerResponse(
            circuit_breaker=True,
            message=f"鐔旀柇宸茶Е鍙? {body.reason or 'manual'}"
        )
    elif body.action == "reset":
        risk_model.reset_circuit_breaker()
        return CircuitBreakerResponse(
            circuit_breaker=False,
            message="鐔旀柇宸茶В闄?
        )
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")


@router.post("/risk-bypass", response_model=RiskBypassResponse)
async def control_risk_bypass(
    current_user: CurrentUser,
    body: RiskBypassRequest,
):
    """
    鎺у埗绯荤粺椋庢帶寮€鍏?

    - enabled=true: 鍏抽棴绯荤粺椋庢帶 (绛栫暐鑷绠＄悊椋庨櫓)
    - enabled=false: 鎭㈠绯荤粺椋庢帶
    """
    risk_model = _get_risk_model()

    if not risk_model:
        from app.services.risk.risk_model import RiskModel
        risk_model = RiskModel()

    risk_model.set_risk_bypass(body.enabled)

    if body.enabled:
        return RiskBypassResponse(
            risk_bypass=True,
            message="鈿狅笍 绯荤粺椋庢帶宸插叧闂? 鎵€鏈変氦鏄撳皢鐢辩瓥鐣ヨ嚜琛岀鐞嗛闄?
        )
    else:
        return RiskBypassResponse(
            risk_bypass=False,
            message="鉁?绯荤粺椋庢帶宸叉仮澶?
        )
