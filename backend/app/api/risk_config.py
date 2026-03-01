"""
Risk Config API
================
风控配置中心 API — 读取和更新 risk_config.yaml

端点:
    GET  /api/risk-config/     - 读取当前配置
    PUT  /api/risk-config/     - 更新配置 (写入 YAML)
"""

from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser
from app.core.risk_config import risk_config


router = APIRouter(tags=["RiskConfig"])


# ==================== Schemas ====================

class RiskConfigResponse(BaseModel):
    """风控配置响应"""
    max_leverage: int
    max_daily_loss_pct: float
    risk_percent: float
    default_leverage: int
    max_positions: int
    default_sl_pct: float
    default_tp_pct: float
    kelly_fraction: float
    max_risk_percent: float
    blacklist: List[str]


class RiskConfigUpdateRequest(BaseModel):
    """风控配置更新请求 (所有字段可选)"""
    max_leverage: Optional[int] = Field(None, ge=1, le=125)
    max_daily_loss_pct: Optional[float] = Field(None, ge=1.0, le=100.0)
    risk_percent: Optional[float] = Field(None, ge=1.0, le=100.0)
    default_leverage: Optional[int] = Field(None, ge=1, le=125)
    max_positions: Optional[int] = Field(None, ge=1, le=50)
    default_sl_pct: Optional[float] = Field(None, ge=0.1, le=50.0)
    default_tp_pct: Optional[float] = Field(None, ge=0.1, le=100.0)
    kelly_fraction: Optional[float] = Field(None, ge=0.1, le=1.0)
    max_risk_percent: Optional[float] = Field(None, ge=1.0, le=100.0)
    blacklist: Optional[List[str]] = None


# ==================== Routes ====================

@router.get("/", response_model=RiskConfigResponse)
async def get_risk_config(current_user: CurrentUser):
    """读取当前用户的风控配置"""
    cfg = risk_config.load_for_user(current_user.id)
    return RiskConfigResponse(**cfg)


@router.put("/", response_model=RiskConfigResponse)
async def update_risk_config(
    request: RiskConfigUpdateRequest,
    current_user: CurrentUser,
):
    """
    更新风控配置 (写入 YAML 文件)
    
    只更新请求中包含的字段，其余保持不变。
    修改立即生效，无需重启系统。
    """
    import yaml
    from loguru import logger
    
    # 读取当前用户的配置
    current = dict(risk_config.load_for_user(current_user.id))
    
    # 合并更新
    update_data = request.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    
    current.update(update_data)
    
    # 写入用户专属配置文件
    try:
        risk_config.save_for_user(current_user.id, current, _generate_yaml)
        
        # 重新加载验证
        new_cfg = risk_config.load_for_user(current_user.id)
        
        logger.info(
            f"[RiskConfig] 用户 {current_user.id} 配置已更新: "
            f"{list(update_data.keys())}"
        )
        
        return RiskConfigResponse(**new_cfg)
        
    except Exception as e:
        logger.error(f"[RiskConfig] 写入失败: {e}")
        raise HTTPException(status_code=500, detail=f"配置写入失败: {str(e)}")


def _generate_yaml(cfg: dict) -> str:
    """生成带中文注释的 YAML 配置文件"""
    lines = [
        "# ==========================================",
        "# 🎛️ 老板风控配置中心",
        "# ==========================================",
        "# 修改后无需重启系统，每次下单自动读取最新值",
        "# ==========================================",
        "",
        "# --- 账户级防爆 ---",
        f"max_leverage: {cfg['max_leverage']}              # 最大杠杆倍数",
        f"max_daily_loss_pct: {cfg['max_daily_loss_pct']}      # 日最大亏损百分比",
        "",
        "# --- 仓位管理 ---",
        f"risk_percent: {cfg['risk_percent']}            # 每次下单使用可用余额的百分比",
        f"default_leverage: {cfg['default_leverage']}           # 默认杠杆倍数",
        f"max_positions: {cfg['max_positions']}              # 最大同时持仓数",
        f"default_sl_pct: {cfg['default_sl_pct']}           # 默认止损百分比",
        f"default_tp_pct: {cfg['default_tp_pct']}           # 默认止盈百分比",
        "",
        "# --- Kelly 模式 (高级) ---",
        f"kelly_fraction: {cfg['kelly_fraction']}           # Kelly 半仓比例",
        f"max_risk_percent: {cfg['max_risk_percent']}        # 单笔最大资金比例",
        "",
        "# --- 品种黑名单 ---",
    ]
    
    blacklist = cfg.get("blacklist", [])
    if blacklist:
        lines.append("blacklist:")
        for item in blacklist:
            lines.append(f"  - {item}")
    else:
        lines.append("blacklist: []")
    
    lines.append("")
    return "\n".join(lines)
