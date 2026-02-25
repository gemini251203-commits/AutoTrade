"""
Pipeline API
==============
四层流水线管理端点

端点:
    GET  /api/pipeline/status   - 获取 Pipeline 实时状态
    GET  /api/pipeline/config   - 获取当前配置
    POST /api/pipeline/circuit-breaker - 熔断控制
"""

from typing import Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DbSession, CurrentUser

router = APIRouter(tags=["Pipeline"])


# ==================== Schemas ====================

class LayerStatus(BaseModel):
    """单层状态"""
    name: str
    status: str        # "active" | "idle" | "error" | "disabled"
    detail: str = ""
    count: int = 0     # 处理次数


class PipelineStatusResponse(BaseModel):
    """Pipeline 整体状态"""
    is_active: bool
    circuit_breaker: bool           # 是否熔断
    risk_bypass: bool = False       # 风控是否已关闭
    uptime_seconds: float
    layers: List[LayerStatus]       # 四层状态
    stats: Dict                     # 流水线统计
    recent_insights: List[Dict]     # 最近信号
    recent_verdicts: List[Dict]     # 最近风控决策


class PipelineConfigResponse(BaseModel):
    """Pipeline 配置"""
    portfolio_model: str            # "fixed_percent" | "kelly"
    risk_percent: float             # 仓位百分比
    default_leverage: int
    max_positions: int
    max_leverage: int
    max_daily_loss_pct: float
    max_total_exposure_pct: float
    blacklist: List[str]


class PipelineConfigUpdate(BaseModel):
    """更新 Pipeline 配置"""
    portfolio_model: Optional[str] = None
    risk_percent: Optional[float] = None
    default_leverage: Optional[int] = None
    max_positions: Optional[int] = None
    max_leverage: Optional[int] = None
    max_daily_loss_pct: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    blacklist: Optional[List[str]] = None


class CircuitBreakerRequest(BaseModel):
    """熔断控制"""
    action: str                     # "trigger" | "reset"
    reason: str = ""


class CircuitBreakerResponse(BaseModel):
    circuit_breaker: bool
    message: str


class RiskBypassRequest(BaseModel):
    """风控开关"""
    enabled: bool                   # True=关闭风控, False=恢复风控


class RiskBypassResponse(BaseModel):
    risk_bypass: bool
    message: str


# ==================== Helper: 获取真实 Pipeline 实例 ====================

_startup_time = datetime.utcnow()
_recent_insights: list = []
_recent_verdicts: list = []


def _get_pipeline():
    """获取全局 TradingPipeline 实例 (来自 core/pipeline.py)"""
    try:
        from app.core.pipeline import get_pipeline
        return get_pipeline()
    except Exception:
        return None


def _get_risk_model():
    """获取当前 Pipeline 中的 RiskModel"""
    pipeline = _get_pipeline()
    return pipeline._risk if pipeline else None


def record_insight(data: dict):
    """记录最近的 Insight (供 EventBus 回调使用)"""
    global _recent_insights
    _recent_insights.append({
        **data,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    if len(_recent_insights) > 50:
        _recent_insights = _recent_insights[-50:]


def record_verdict(data: dict):
    """记录最近的风控决策"""
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
    获取 Pipeline 实时状态

    混合数据源:
    - DB 查询: 策略数、订单数、仓位数 (持久化, 不随重启丢失)
    - 内存统计: 本次运行期间的流水线计数 (辅助)
    """
    from sqlalchemy import select, func
    from app.models.order import Order, OrderStatus
    from app.models.position import Position, PositionStatus
    from app.models.strategy import Strategy

    pipeline = _get_pipeline()
    risk_model = _get_risk_model()

    # 计算运行时间
    uptime = (datetime.utcnow() - _startup_time).total_seconds()

    # 从 Pipeline 获取内存统计 (本次运行)
    mem_stats = {}
    if pipeline:
        mem_stats = pipeline.get_stats()

    # ===== 从 DB 获取真实持久化统计 =====
    user_id = current_user.id

    # Alpha: 活跃策略数
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

    # Portfolio/Risk/Execution: 订单统计
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

    # 仓位统计
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

    # 合并统计
    alpha_count = strategy_count + mem_stats.get("insights_generated", 0)
    portfolio_count = total_orders  # 每个订单都经过 Portfolio 计算
    risk_count = filled_orders + rejected_orders + mem_stats.get("risk_approved", 0) + mem_stats.get("risk_rejected", 0)
    exec_count = filled_orders + mem_stats.get("orders_executed", 0)

    is_active = total_orders > 0 or strategy_count > 0

    # 熔断 / 风控旁路状态
    circuit_breaker = False
    risk_bypass = False
    if risk_model:
        circuit_breaker = risk_model.is_circuit_breaker_active
        risk_bypass = risk_model.risk_bypass

    # 构造四层状态
    layers = []

    # Alpha 层
    alpha_detail = f"{strategy_count} 个活跃策略"
    if pipeline and pipeline._alphas:
        alpha_names = [a.get_name() for a in pipeline._alphas]
        alpha_detail += f" · Models: {', '.join(alpha_names)}"
    layers.append(LayerStatus(
        name="Alpha",
        status="active" if strategy_count > 0 else "idle",
        detail=alpha_detail,
        count=alpha_count,
    ))

    # Portfolio 层
    portfolio_model = pipeline._portfolio if pipeline else None
    portfolio_type = type(portfolio_model).__name__ if portfolio_model else "FixedPercentModel"
    layers.append(LayerStatus(
        name="Portfolio",
        status="active" if is_active else "idle",
        detail=f"Model: {portfolio_type} · {total_orders} 笔订单",
        count=portfolio_count,
    ))

    # Risk 层
    risk_status = "active"
    if circuit_breaker:
        risk_status = "error"
    elif risk_bypass:
        risk_status = "disabled"
    elif not is_active:
        risk_status = "idle"
    
    risk_detail = f"通过: {filled_orders}, 拒绝: {rejected_orders}"
    if circuit_breaker:
        risk_detail += " ⚠️ 熔断中"
    elif risk_bypass:
        risk_detail += " ⚠️ 风控已关闭"
    
    layers.append(LayerStatus(
        name="Risk",
        status=risk_status,
        detail=risk_detail,
        count=risk_count,
    ))

    # Execution 层
    layers.append(LayerStatus(
        name="Execution",
        status="active" if exec_count > 0 else "idle",
        detail=f"已执行: {filled_orders} · 持仓: {open_positions} · 已平: {closed_positions}",
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
    """获取当前 Pipeline 配置 (从真实实例读取)"""
    pipeline = _get_pipeline()
    portfolio_model = pipeline._portfolio if pipeline else None
    risk_model = _get_risk_model()

    # 默认值
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

    # 从实际模型读取
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
    控制风控熔断器

    - trigger: 触发熔断 (停止一切交易)
    - reset: 解除熔断
    """
    risk_model = _get_risk_model()

    if not risk_model:
        from app.services.risk.risk_model import RiskModel
        risk_model = RiskModel()

    if body.action == "trigger":
        risk_model.trigger_circuit_breaker(body.reason)
        return CircuitBreakerResponse(
            circuit_breaker=True,
            message=f"熔断已触发: {body.reason or 'manual'}"
        )
    elif body.action == "reset":
        risk_model.reset_circuit_breaker()
        return CircuitBreakerResponse(
            circuit_breaker=False,
            message="熔断已解除"
        )
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")


@router.post("/risk-bypass", response_model=RiskBypassResponse)
async def control_risk_bypass(
    current_user: CurrentUser,
    body: RiskBypassRequest,
):
    """
    控制系统风控开关

    - enabled=true: 关闭系统风控 (策略自行管理风险)
    - enabled=false: 恢复系统风控
    """
    risk_model = _get_risk_model()

    if not risk_model:
        from app.services.risk.risk_model import RiskModel
        risk_model = RiskModel()

    risk_model.set_risk_bypass(body.enabled)

    if body.enabled:
        return RiskBypassResponse(
            risk_bypass=True,
            message="⚠️ 系统风控已关闭, 所有交易将由策略自行管理风险"
        )
    else:
        return RiskBypassResponse(
            risk_bypass=False,
            message="✅ 系统风控已恢复"
        )
