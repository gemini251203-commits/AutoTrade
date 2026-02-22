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
        "timestamp": datetime.utcnow().isoformat(),
    })
    if len(_recent_insights) > 50:
        _recent_insights = _recent_insights[-50:]


def record_verdict(data: dict):
    """记录最近的风控决策"""
    global _recent_verdicts
    _recent_verdicts.append({
        **data,
        "timestamp": datetime.utcnow().isoformat(),
    })
    if len(_recent_verdicts) > 50:
        _recent_verdicts = _recent_verdicts[-50:]


# ==================== Routes ====================

@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    current_user: CurrentUser,
):
    """
    获取 Pipeline 实时状态

    从 core/pipeline.py 的全局 TradingPipeline 实例读取真实统计数据
    """
    pipeline = _get_pipeline()
    risk_model = _get_risk_model()

    # 计算运行时间
    uptime = (datetime.utcnow() - _startup_time).total_seconds()

    # 从 Pipeline 获取真实统计
    stats = {}
    is_active = False
    if pipeline:
        stats = pipeline.get_stats()
        is_active = stats.get("ticks_processed", 0) > 0 or stats.get("orders_executed", 0) > 0

    # 熔断状态
    circuit_breaker = False
    if risk_model:
        circuit_breaker = risk_model.is_circuit_breaker_active

    # 构造四层状态
    layers = []

    # Alpha 层
    alpha_count = stats.get("insights_generated", 0)
    alpha_detail = ""
    if pipeline and pipeline._alphas:
        alpha_names = [a.get_name() for a in pipeline._alphas]
        alpha_detail = f"Models: {', '.join(alpha_names)}"
    layers.append(LayerStatus(
        name="Alpha",
        status="active" if is_active and alpha_count > 0 else "idle",
        detail=alpha_detail,
        count=alpha_count,
    ))

    # Portfolio 层
    target_count = stats.get("targets_created", 0)
    portfolio_model = pipeline._portfolio if pipeline else None
    portfolio_type = type(portfolio_model).__name__ if portfolio_model else "FixedPercentModel"
    layers.append(LayerStatus(
        name="Portfolio",
        status="active" if is_active and target_count > 0 else "idle",
        detail=f"Model: {portfolio_type}",
        count=target_count,
    ))

    # Risk 层
    approved = stats.get("risk_approved", 0)
    rejected = stats.get("risk_rejected", 0)
    risk_status = "active"
    if circuit_breaker:
        risk_status = "error"
    elif not is_active:
        risk_status = "idle"
    layers.append(LayerStatus(
        name="Risk",
        status=risk_status,
        detail=f"Approved: {approved}, Rejected: {rejected}" + (" CIRCUIT BREAKER" if circuit_breaker else ""),
        count=approved + rejected,
    ))

    # Execution 层
    exec_count = stats.get("orders_executed", 0)
    layers.append(LayerStatus(
        name="Execution",
        status="active" if is_active and exec_count > 0 else "idle",
        detail=f"Orders executed: {exec_count}",
        count=exec_count,
    ))

    return PipelineStatusResponse(
        is_active=is_active,
        circuit_breaker=circuit_breaker,
        uptime_seconds=uptime,
        layers=layers,
        stats=stats,
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
