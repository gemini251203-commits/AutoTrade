"""
Pipeline API
==============
四层流水线管理端点

端点:
    GET  /api/pipeline/status   - 获取 Pipeline 实时状态
    GET  /api/pipeline/config   - 获取当前配置
    POST /api/pipeline/config   - 更新配置
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


# ==================== Singleton Registry ====================

class PipelineRegistry:
    """
    Pipeline 全局注册表 — 管理四层组件实例
    
    在 startup 时初始化, API 端点读取状态
    """
    
    _instance = None
    
    def __init__(self):
        self.pipeline = None
        self.risk_model = None
        self.portfolio_model = None
        self.startup_time = datetime.utcnow()
        self._recent_insights: list = []
        self._recent_verdicts: list = []
    
    @classmethod
    def get(cls) -> "PipelineRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def record_insight(self, data: dict):
        """记录最近的 Insight"""
        self._recent_insights.append({
            **data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        # 只保留最近 50 条
        if len(self._recent_insights) > 50:
            self._recent_insights = self._recent_insights[-50:]
    
    def record_verdict(self, data: dict):
        """记录最近的风控决策"""
        self._recent_verdicts.append({
            **data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(self._recent_verdicts) > 50:
            self._recent_verdicts = self._recent_verdicts[-50:]
    
    def get_recent_insights(self, limit: int = 20) -> list:
        return list(reversed(self._recent_insights[-limit:]))
    
    def get_recent_verdicts(self, limit: int = 20) -> list:
        return list(reversed(self._recent_verdicts[-limit:]))


# 全局实例
pipeline_registry = PipelineRegistry.get()


# ==================== Routes ====================

@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    current_user: CurrentUser,
):
    """
    获取 Pipeline 实时状态
    
    返回四层 (Alpha, Portfolio, Risk, Execution) 的运行状态和统计
    """
    reg = pipeline_registry
    
    # 计算运行时间
    uptime = (datetime.utcnow() - reg.startup_time).total_seconds()
    
    # 从 Pipeline 获取统计
    stats = {}
    is_active = False
    if reg.pipeline:
        stats = reg.pipeline.get_stats()
        is_active = True
    
    # 熔断状态
    circuit_breaker = False
    if reg.risk_model:
        circuit_breaker = reg.risk_model.is_circuit_breaker_active
    
    # 构造四层状态
    layers = []
    
    # Alpha 层
    alpha_count = stats.get("insights_generated", 0)
    alpha_detail = ""
    if reg.pipeline:
        alpha_names = [a.get_name() for a in reg.pipeline._alphas]
        alpha_detail = f"Models: {', '.join(alpha_names)}"
    layers.append(LayerStatus(
        name="Alpha",
        status="active" if is_active and alpha_count > 0 else "idle",
        detail=alpha_detail,
        count=alpha_count,
    ))
    
    # Portfolio 层
    target_count = stats.get("targets_created", 0)
    portfolio_type = "fixed_percent"
    if reg.portfolio_model:
        portfolio_type = type(reg.portfolio_model).__name__
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
        detail=f"Approved: {approved}, Rejected: {rejected}" + (" 🚨 CIRCUIT BREAKER" if circuit_breaker else ""),
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
        recent_insights=reg.get_recent_insights(20),
        recent_verdicts=reg.get_recent_verdicts(20),
    )


@router.get("/config", response_model=PipelineConfigResponse)
async def get_pipeline_config(
    current_user: CurrentUser,
):
    """获取当前 Pipeline 配置"""
    reg = pipeline_registry
    
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
    if reg.portfolio_model:
        from app.services.portfolio.model import FixedPercentModel, KellyPortfolioModel
        if isinstance(reg.portfolio_model, FixedPercentModel):
            config.portfolio_model = "fixed_percent"
            config.risk_percent = reg.portfolio_model._risk_percent
            config.default_leverage = reg.portfolio_model._default_leverage
            config.max_positions = reg.portfolio_model._max_positions
        elif isinstance(reg.portfolio_model, KellyPortfolioModel):
            config.portfolio_model = "kelly"
            config.default_leverage = reg.portfolio_model._default_leverage
            config.max_positions = reg.portfolio_model._max_positions
    
    if reg.risk_model:
        config.max_leverage = reg.risk_model._config.max_leverage
        config.max_daily_loss_pct = reg.risk_model._config.max_daily_loss_pct
        config.max_total_exposure_pct = reg.risk_model._config.max_total_exposure_pct
        config.blacklist = reg.risk_model._config.blacklist
    
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
    reg = pipeline_registry
    
    if not reg.risk_model:
        # 没有 Pipeline, 创建临时 RiskModel
        from app.services.risk.risk_model import RiskModel
        reg.risk_model = RiskModel()
    
    if body.action == "trigger":
        reg.risk_model.trigger_circuit_breaker(body.reason)
        return CircuitBreakerResponse(
            circuit_breaker=True,
            message=f"🚨 熔断已触发: {body.reason or 'manual'}"
        )
    elif body.action == "reset":
        reg.risk_model.reset_circuit_breaker()
        return CircuitBreakerResponse(
            circuit_breaker=False,
            message="✅ 熔断已解除"
        )
    else:
        raise HTTPException(400, f"Unknown action: {body.action}")
