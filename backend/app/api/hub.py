"""
Agent Hub API
==============
智能体中枢 API 路由

路由前缀: /api/hub
端点:
  GET    /agents                  → 列出智能体
  POST   /agents                  → 创建智能体
  PUT    /agents/{agent_id}       → 更新智能体
  DELETE /agents/{agent_id}       → 删除智能体
  POST   /agents/{agent_id}/activate → 激活/停止
  GET    /status                  → Hub 全局状态
  POST   /agents/{agent_id}/chat  → SSE 对话 (独裁者)
  POST   /board/deliberate        → 多 AI 辩论 (董事会)
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func

from app.api.deps import CurrentUser, DbSession
from app.models.hub_agent import HubAgent, HubAgentStatus
from app.core.time_utils import utc_now

router = APIRouter(prefix="/hub", tags=["Agent Hub"])


# ============================================================
# Pydantic Schemas (契约层)
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


class HubAgentActionRequest(BaseModel):
    """智能体动作请求"""
    action: str  # "start" | "stop" | "run_once"


class HubAgentResponse(BaseModel):
    """智能体响应 (不含 api_key_enc)"""
    id: int
    name: str
    role: str
    avatar: str
    provider: str
    model: str
    api_base_url: Optional[str]
    system_prompt: str
    temperature: float
    status: str
    is_active: bool
    last_run_at: Optional[str]
    last_error: Optional[str]
    total_runs: int
    total_trades: int
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


class HubBoardRequest(BaseModel):
    """董事会辩论请求"""
    topic: str
    symbol: str = "BTCUSDT"


class HubChatRequest(BaseModel):
    """对话请求"""
    message: str


# ============================================================
# Helper: ORM → Response
# ============================================================

def _agent_to_response(agent: HubAgent) -> HubAgentResponse:
    """将 ORM 对象转换为 Response (安全: 不暴露 api_key_enc)"""
    return HubAgentResponse(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        avatar=agent.avatar,
        provider=agent.provider,
        model=agent.model,
        api_base_url=agent.api_base_url,
        system_prompt=agent.system_prompt,
        temperature=agent.temperature,
        status=agent.status.value if isinstance(agent.status, HubAgentStatus) else agent.status,
        is_active=agent.is_active,
        last_run_at=agent.last_run_at.isoformat() if agent.last_run_at else None,
        last_error=agent.last_error,
        total_runs=agent.total_runs,
        total_trades=agent.total_trades,
        created_at=agent.created_at.isoformat() if agent.created_at else "",
        updated_at=agent.updated_at.isoformat() if agent.updated_at else "",
    )


# ============================================================
# Helper: API Key 加密/解密
# ============================================================

def _encrypt_key(plain: str) -> str:
    """加密 API Key (复用系统加密方案)"""
    try:
        from app.core.encryption import encrypt_value
        return encrypt_value(plain)
    except ImportError:
        # Fallback: 简单 base64 (生产环境应使用 Fernet)
        import base64
        return base64.b64encode(plain.encode()).decode()


def _decrypt_key(encrypted: str) -> str:
    """解密 API Key"""
    try:
        from app.core.encryption import decrypt_value
        return decrypt_value(encrypted)
    except ImportError:
        import base64
        return base64.b64decode(encrypted.encode()).decode()


# ============================================================
# 路由: CRUD
# ============================================================

@router.get("/agents", response_model=HubAgentListResponse)
async def list_agents(
    current_user: CurrentUser,
    db: DbSession,
):
    """列出当前用户的所有智能体"""
    result = await db.execute(
        select(HubAgent)
        .where(HubAgent.user_id == current_user.id)
        .order_by(HubAgent.created_at.desc())
    )
    agents = result.scalars().all()
    return HubAgentListResponse(
        agents=[_agent_to_response(a) for a in agents]
    )


@router.post("/agents", response_model=HubAgentResponse, status_code=201)
async def create_agent(
    body: HubAgentCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """创建新智能体"""
    agent = HubAgent(
        user_id=current_user.id,
        name=body.name,
        role=body.role,
        avatar=body.avatar,
        provider=body.provider,
        model=body.model,
        api_base_url=body.api_base_url,
        api_key_enc=_encrypt_key(body.api_key) if body.api_key else None,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return _agent_to_response(agent)


@router.put("/agents/{agent_id}", response_model=HubAgentResponse)
async def update_agent(
    agent_id: int,
    body: HubAgentUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """更新智能体配置"""
    result = await db.execute(
        select(HubAgent).where(
            HubAgent.id == agent_id,
            HubAgent.user_id == current_user.id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    # 逐字段更新 (仅非 None 的字段)
    update_data = body.model_dump(exclude_unset=True)
    
    # 特殊处理 api_key → api_key_enc
    if "api_key" in update_data:
        api_key = update_data.pop("api_key")
        if api_key:
            agent.api_key_enc = _encrypt_key(api_key)
    
    for field, value in update_data.items():
        if hasattr(agent, field):
            setattr(agent, field, value)
    
    agent.updated_at = utc_now()
    await db.commit()
    await db.refresh(agent)
    return _agent_to_response(agent)


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """删除智能体"""
    user_id = current_user.id
    result = await db.execute(
        select(HubAgent).where(
            HubAgent.id == agent_id,
            HubAgent.user_id == user_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    # 如果正在运行, 先停止
    if agent.is_active:
        try:
            from app.services.hub.daemon import hub_daemon
            await hub_daemon.stop_agent(user_id, agent_id)
        except Exception:
            pass
    
    await db.delete(agent)
    await db.commit()
    return {"success": True}


# ============================================================
# 路由: 运行控制
# ============================================================

@router.post("/agents/{agent_id}/activate", response_model=HubAgentResponse)
async def control_agent(
    agent_id: int,
    body: HubAgentActionRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """激活/停止/单次执行智能体"""
    user_id = current_user.id
    result = await db.execute(
        select(HubAgent).where(
            HubAgent.id == agent_id,
            HubAgent.user_id == user_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    from app.services.hub.daemon import hub_daemon
    
    if body.action == "start":
        agent.is_active = True
        agent.status = HubAgentStatus.ACTIVE
        agent.last_error = None
        await db.commit()
        await db.refresh(agent)
        # 通知 daemon 拉起
        await hub_daemon.start_agent(user_id, agent)
        
    elif body.action == "stop":
        agent.is_active = False
        agent.status = HubAgentStatus.IDLE
        await db.commit()
        await db.refresh(agent)
        await hub_daemon.stop_agent(user_id, agent_id)
        
    elif body.action == "run_once":
        await hub_daemon.run_agent_once(user_id, agent, db)
        await db.refresh(agent)
        
    else:
        raise HTTPException(status_code=400, detail=f"未知动作: {body.action}")
    
    return _agent_to_response(agent)


@router.get("/status", response_model=HubStatusResponse)
async def get_hub_status(
    current_user: CurrentUser,
    db: DbSession,
):
    """获取 Hub 全局状态"""
    user_id = current_user.id
    
    # 总数
    total_result = await db.execute(
        select(func.count(HubAgent.id)).where(HubAgent.user_id == user_id)
    )
    total_agents = total_result.scalar() or 0
    
    # 活跃列表
    active_result = await db.execute(
        select(HubAgent).where(
            HubAgent.user_id == user_id,
            HubAgent.is_active == True,
        )
    )
    active_agents = active_result.scalars().all()
    active_count = len(active_agents)
    
    # 动态判断模式
    if active_count == 0:
        mode = "idle"
    elif active_count == 1:
        mode = "dictator"
    else:
        mode = "board"
    
    return HubStatusResponse(
        mode=mode,
        active_count=active_count,
        total_agents=total_agents,
        active_agents=[_agent_to_response(a) for a in active_agents],
    )


# ============================================================
# 路由: 独裁者对话 (SSE)
# ============================================================

@router.post("/agents/{agent_id}/chat")
async def chat_with_agent(
    agent_id: int,
    body: HubChatRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """与智能体 SSE 对话 (独裁者模式)"""
    user_id = current_user.id
    result = await db.execute(
        select(HubAgent).where(
            HubAgent.id == agent_id,
            HubAgent.user_id == user_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    
    from app.services.hub.brain import hub_brain
    
    async def event_generator():
        """SSE 事件生成器"""
        try:
            async for event in hub_brain.chat_stream(
                agent=agent,
                message=body.message,
                db=db,
                user_id=user_id,
            ):
                yield f"data: {event}\n\n"
        except Exception as e:
            import json
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 路由: 董事会辩论
# ============================================================

@router.post("/board/deliberate")
async def board_deliberate(
    body: HubBoardRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """多 AI 董事会辩论"""
    user_id = current_user.id
    
    # 获取所有 active 智能体
    result = await db.execute(
        select(HubAgent).where(
            HubAgent.user_id == user_id,
            HubAgent.is_active == True,
        )
    )
    active_agents = result.scalars().all()
    
    if len(active_agents) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"董事会模式需要至少 2 个激活的智能体 (当前: {len(active_agents)})",
        )
    
    from app.services.hub.board import hub_board
    
    board_result = await hub_board.deliberate(
        agents=active_agents,
        topic=body.topic,
        symbol=body.symbol,
        db=db,
        user_id=user_id,
    )
    
    return board_result
