"""
Hub Schemas
============
Agent Hub 的 Pydantic 请求/响应模型

从 api/hub.py 抽取至此，保持 API 层纯粹只做路由。
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# ============================================================
# 请求 Schemas
# ============================================================

class HubAgentCreateRequest(BaseModel):
    """创建智能体请求"""
    name: str
    role: str = "trader"
    avatar: str = "BOT"
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None    # 明文入, 后端加密
    system_prompt: str = ""
    temperature: float = 0.7
    polling_interval: int = 5
    allowed_tools: Optional[List[str]] = None  # null=全部, []=禁用, ["get_price",...]=指定


class HubAgentUpdateRequest(BaseModel):
    """更新智能体请求"""
    name: Optional[str] = None
    role: Optional[str] = None
    avatar: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None    # 非空时重新加密
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    polling_interval: Optional[int] = None
    allowed_tools: Optional[List[str]] = None  # 显式设置, 覆盖旧值
    active_template_id: Optional[int] = None    # 绑定提示词模板


class HubAgentActionRequest(BaseModel):
    """智能体动作请求"""
    action: str  # "start" | "stop" | "run_once"


class HubChatRequest(BaseModel):
    """对话请求"""
    message: str


class HubBoardRequest(BaseModel):
    """董事会辩论请求"""
    topic: str
    symbol: str = "BTCUSDT"


class HubLogSaveRequest(BaseModel):
    """前端保存日志请求"""
    agent_id: Optional[int] = None
    agent_name: str = "System"
    log_type: str = "system"
    content: str


class SecretarySettingRequest(BaseModel):
    agent_id: Optional[int] = None


# ============================================================
# 响应 Schemas
# ============================================================

class HubAgentResponse(BaseModel):
    """智能体响应 (不含 api_key_enc)"""
    id: int
    name: str
    role: str
    avatar: str
    provider: str
    model: str
    api_base_url: Optional[str]
    has_api_key: bool = False
    system_prompt: str
    temperature: float
    status: str
    is_active: bool
    last_run_at: Optional[str]
    last_error: Optional[str]
    total_runs: int
    total_trades: int
    polling_interval: int = 5
    allowed_tools: Optional[List[str]] = None
    active_template_id: Optional[int] = None
    created_at: str
    updated_at: str
    
    model_config = ConfigDict(from_attributes=True)


class HubAgentListResponse(BaseModel):
    """智能体列表响应"""
    agents: List[HubAgentResponse]


class HubStatusResponse(BaseModel):
    """Hub 全局状态响应"""
    mode: str            # "dictator" | "board" | "idle"
    active_count: int
    total_agents: int
    active_agents: List[HubAgentResponse]


class HubLogEntry(BaseModel):
    """日志条目"""
    id: int
    agent_id: Optional[int]
    agent_name: str
    log_type: str
    content: str
    created_at: str
    
    model_config = ConfigDict(from_attributes=True)
