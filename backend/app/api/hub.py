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

router = APIRouter(tags=["Agent Hub"])


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
        has_api_key=bool(agent.api_key_enc),
        system_prompt=agent.system_prompt,
        temperature=agent.temperature,
        status=agent.status.value if isinstance(agent.status, HubAgentStatus) else agent.status,
        is_active=agent.is_active,
        last_run_at=agent.last_run_at.isoformat() if agent.last_run_at else None,
        last_error=agent.last_error,
        total_runs=agent.total_runs,
        total_trades=agent.total_trades,
        polling_interval=agent.polling_interval if hasattr(agent, 'polling_interval') else 5,
        allowed_tools=agent.allowed_tools if hasattr(agent, 'allowed_tools') else None,
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
    """解密 API Key — 自动兼容多种加密格式"""
    if not encrypted:
        return ""
    # 方法 1: Fernet
    try:
        from app.core.encryption import decrypt_api_key
        return decrypt_api_key(encrypted)
    except Exception:
        pass
    # 方法 2: Base64
    try:
        import base64
        decoded = base64.b64decode(encrypted.encode()).decode()
        if decoded and decoded.isprintable() and len(decoded) > 5:
            return decoded
    except Exception:
        pass
    # 方法 3: 原始值
    if encrypted.startswith("sk-") or len(encrypted) > 20:
        return encrypted
    raise ValueError("Decryption failed")


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
        polling_interval=body.polling_interval,
        allowed_tools=body.allowed_tools,
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
        import asyncio
        
        async def _bg_run_once():
            """后台单次执行 (独立 DB session)"""
            try:
                from app.db.session import AsyncSessionLocal
                async with AsyncSessionLocal() as bg_db:
                    result = await bg_db.execute(
                        select(HubAgent).where(HubAgent.id == agent_id)
                    )
                    bg_agent = result.scalar_one_or_none()
                    if bg_agent:
                        await hub_daemon.run_agent_once(user_id, bg_agent, bg_db)
                        await bg_db.commit()
            except Exception as e:
                print(f"[Hub] run_once background error: {e}")
        
        asyncio.create_task(_bg_run_once())
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
        """SSE 事件生成器 (含心跳保活)"""
        import json as _json
        import asyncio as _asyncio
        
        # 心跳任务: 每15秒发送 ping 防止代理超时
        last_event = _asyncio.get_event_loop().time()
        heartbeat_interval = 15  # 秒
        
        async def _stream_with_heartbeat():
            nonlocal last_event
            try:
                async for event in hub_brain.chat_stream(
                    agent=agent,
                    message=body.message,
                    db=db,
                    user_id=user_id,
                ):
                    last_event = _asyncio.get_event_loop().time()
                    yield f"data: {event}\n\n"
            except Exception as e:
                yield f"data: {_json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        
        # 使用异步队列合并数据事件和心跳
        queue: _asyncio.Queue = _asyncio.Queue()
        done = False
        
        async def _producer():
            nonlocal done
            async for chunk in _stream_with_heartbeat():
                await queue.put(chunk)
            done = True
            await queue.put(None)  # sentinel
        
        async def _heartbeat():
            nonlocal last_event
            while not done:
                await _asyncio.sleep(heartbeat_interval)
                if not done:
                    elapsed = _asyncio.get_event_loop().time() - last_event
                    if elapsed >= heartbeat_interval - 1:
                        await queue.put(f"data: {_json.dumps({'type': 'ping'})}\n\n")
        
        producer_task = _asyncio.create_task(_producer())
        heartbeat_task = _asyncio.create_task(_heartbeat())
        
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            heartbeat_task.cancel()
            if not producer_task.done():
                producer_task.cancel()
    
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


# ============================================================
# 路由: War Room 日志
# ============================================================

class HubLogEntry(BaseModel):
    """日志条目"""
    id: int
    agent_id: Optional[int]
    agent_name: str
    log_type: str
    content: str
    created_at: str
    
    model_config = ConfigDict(from_attributes=True)


class HubLogSaveRequest(BaseModel):
    """前端保存日志请求"""
    agent_id: Optional[int] = None
    agent_name: str = "System"
    log_type: str = "system"
    content: str


@router.get("/logs")
async def get_hub_logs(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
    keyword: Optional[str] = None,
    agent_id: Optional[int] = None,
):
    """获取 War Room 历史日志 (支持关键词搜索和分页)"""
    from app.models.hub_log import HubLog
    
    base_filter = [
        HubLog.user_id == current_user.id,
        HubLog.log_type.notin_(["tool_call", "tool_result"]),
    ]
    if keyword:
        base_filter.append(HubLog.content.ilike(f"%{keyword}%"))
    if agent_id:
        base_filter.append(HubLog.agent_id == agent_id)
    
    # limit+1 技巧: 多取 1 条判断是否有下一页, 避免 COUNT 慢查询
    query = (
        select(HubLog)
        .where(*base_filter)
        .order_by(HubLog.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    result = await db.execute(query)
    logs = list(result.scalars().all())
    
    has_more = len(logs) > limit
    if has_more:
        logs = logs[:limit]
    
    return {
        "has_more": has_more,
        "page_size": limit,
        "logs": [
            {
                "id": log.id,
                "agent_id": log.agent_id,
                "agent_name": log.agent_name,
                "log_type": log.log_type,
                "content": log.content,
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in logs
        ]
    }


@router.post("/logs")
async def save_hub_log(
    body: HubLogSaveRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """前端保存一条 War Room 日志"""
    from app.models.hub_log import HubLog
    
    log = HubLog(
        user_id=current_user.id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        log_type=body.log_type,
        content=body.content,
    )
    db.add(log)
    await db.commit()
    return {"success": True, "id": log.id}


@router.delete("/logs")
async def clear_hub_logs(
    current_user: CurrentUser,
    db: DbSession,
):
    """清空当前用户的所有 War Room 日志"""
    from app.models.hub_log import HubLog
    from sqlalchemy import delete
    
    await db.execute(
        delete(HubLog).where(HubLog.user_id == current_user.id)
    )
    await db.commit()
    return {"success": True, "message": "日志已清空"}


# ============================================================
# 路由: 记忆坍缩引擎
# ============================================================

@router.post("/memory/consolidate")
async def trigger_consolidation(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    手动触发记忆坍缩 — CEO 一键生成今日《董事会纪要》
    自动读取指定书记员 Agent 的配置
    """
    from app.services.hub.consolidator import memory_consolidator
    
    # 读取指定书记员
    secretary_agent_id = None
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        val = await r.get(f"hub:secretary:{current_user.id}")
        await r.close()
        if val:
            secretary_agent_id = int(val)
    except Exception:
        pass
    
    try:
        result = await memory_consolidator.consolidate(
            current_user.id,
            secretary_agent_id=secretary_agent_id,
        )
        return {
            "success": True,
            "summary": result.get("summary", ""),
            "key_lessons": result.get("key_lessons", ""),
            "importance": result.get("importance", 5),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"坍缩失败: {str(e)}")


class SecretarySettingRequest(BaseModel):
    agent_id: Optional[int] = None


@router.post("/settings/secretary")
async def set_secretary(
    body: SecretarySettingRequest,
    current_user: CurrentUser,
):
    """指定首席书记员 Agent"""
    import redis.asyncio as aioredis
    from app.core.config import settings
    
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    key = f"hub:secretary:{current_user.id}"
    if body.agent_id:
        await r.set(key, str(body.agent_id))
    else:
        await r.delete(key)
    await r.close()
    
    return {"success": True, "secretary_agent_id": body.agent_id}


@router.get("/settings/secretary")
async def get_secretary(
    current_user: CurrentUser,
):
    """获取当前首席书记员"""
    import redis.asyncio as aioredis
    from app.core.config import settings
    
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    val = await r.get(f"hub:secretary:{current_user.id}")
    await r.close()
    
    return {"secretary_agent_id": int(val) if val else None}


@router.get("/memory/minutes")
async def get_board_minutes(
    current_user: CurrentUser,
    db: DbSession,
    days: int = 7,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """
    获取董事会纪要
    
    两种模式:
    - 默认: 近 N 天
    - 月历: 指定 year + month 返回整月纪要
    """
    from app.models.board_minutes import BoardMinutes
    from datetime import date, timedelta
    import calendar as cal_module
    
    if year and month:
        # 月历模式: 返回指定月份所有纪要
        first_day = date(year, month, 1)
        _, last_day_num = cal_module.monthrange(year, month)
        last_day = date(year, month, last_day_num)
        
        result = await db.execute(
            select(BoardMinutes).where(
                BoardMinutes.user_id == current_user.id,
                BoardMinutes.date >= first_day,
                BoardMinutes.date <= last_day,
            ).order_by(BoardMinutes.date.desc())
        )
    else:
        # 近 N 天模式
        cutoff = date.today() - timedelta(days=days)
        result = await db.execute(
            select(BoardMinutes).where(
                BoardMinutes.user_id == current_user.id,
                BoardMinutes.date >= cutoff,
            ).order_by(BoardMinutes.date.desc())
        )
    
    minutes = result.scalars().all()
    
    return {
        "minutes": [
            {
                "id": m.id,
                "date": m.date.isoformat(),
                "summary": m.summary,
                "key_lessons": m.key_lessons,
                "importance": m.importance,
                "trade_count": m.trade_count,
                "pnl_total": m.pnl_total,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in minutes
        ]
    }


# ============================================
# 每日复盘一键导出 (Markdown)
# ============================================

@router.get("/daily-recap")
async def daily_recap(
    db: DbSession,
    current_user: CurrentUser,
    date: Optional[str] = None,
):
    """
    一键提取当天 "冲突、遗憾与战绩"，返回 Markdown 纯文本。
    用于丢给 ChatGPT / 大模型进行二次爆款润色。
    
    Query params:
        date: 可选日期 YYYY-MM-DD (默认今天 CST)
    """
    from datetime import timedelta, timezone, date as date_type
    from decimal import Decimal
    from sqlalchemy import or_, and_
    from app.models.position import Position, PositionStatus
    from app.models.hub_log import HubLog
    from app.models.intercepted_order import InterceptedOrder
    
    _CST = timezone(timedelta(hours=8))
    
    # 解析目标日期
    if date:
        try:
            target = date_type.fromisoformat(date)
        except ValueError:
            raise HTTPException(400, "日期格式错误，请使用 YYYY-MM-DD")
    else:
        target = datetime.now(_CST).date()
    
    # 北京时间 → UTC 范围
    day_start = datetime(target.year, target.month, target.day) - timedelta(hours=8)
    day_end = day_start + timedelta(days=1)
    
    lines = [
        f"# 每日复盘素材 — {target}",
        f"> 自动生成于 {datetime.now(_CST).strftime('%Y-%m-%d %H:%M CST')}，可直接丢给 AI 润色成爆款文案。",
        "",
    ]
    
    # ============ 1. 今日财务看板 ============
    lines.append("---")
    lines.append("## 今日财务看板")
    lines.append("")
    
    # 查询已平仓仓位
    closed_result = await db.execute(
        select(Position).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.CLOSED,
            Position.closed_at >= day_start,
            Position.closed_at < day_end,
        ).order_by(Position.closed_at)
    )
    closed_positions = closed_result.scalars().all()
    
    # 查询仍持仓的
    open_result = await db.execute(
        select(Position).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.OPEN,
            Position.created_at >= day_start,
            Position.created_at < day_end,
        )
    )
    open_positions = open_result.scalars().all()
    
    if closed_positions:
        total_pnl = sum(float(p.realized_pnl or 0) for p in closed_positions)
        win_count = sum(1 for p in closed_positions if (p.realized_pnl or 0) > 0)
        loss_count = sum(1 for p in closed_positions if (p.realized_pnl or 0) < 0)
        total_count = len(closed_positions)
        win_rate = (win_count / total_count * 100) if total_count > 0 else 0
        
        pnls = [float(p.realized_pnl or 0) for p in closed_positions]
        max_win = max(pnls) if pnls else 0
        max_loss = min(pnls) if pnls else 0
        total_commission = sum(float(p.total_commission or 0) for p in closed_positions)
        
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 已平仓笔数 | {total_count} |")
        lines.append(f"| 胜 / 负 | {win_count} / {loss_count} |")
        lines.append(f"| 胜率 | {win_rate:.1f}% |")
        lines.append(f"| 净盈亏 | {total_pnl:+.2f} USDT |")
        lines.append(f"| 最大单笔盈利 | {max_win:+.2f} USDT |")
        lines.append(f"| 最大单笔亏损 | {max_loss:+.2f} USDT |")
        lines.append(f"| 总手续费 | {total_commission:.4f} USDT |")
        lines.append("")
        
        # 逐笔交易明细
        lines.append("### 交易明细")
        lines.append("")
        for p in closed_positions:
            side = p.side.value.upper() if hasattr(p.side, 'value') else str(p.side).upper()
            pnl = float(p.realized_pnl or 0)
            pnl_sign = "+" if pnl >= 0 else ""
            entry = float(p.entry_price or 0)
            close = float(p.close_price or 0) if hasattr(p, 'close_price') and p.close_price else 0
            leverage = p.leverage or 1
            agent = p.agent_name or p.source or "manual"
            open_t = (p.created_at + timedelta(hours=8)).strftime("%H:%M") if p.created_at else "-"
            close_t = (p.closed_at + timedelta(hours=8)).strftime("%H:%M") if p.closed_at else "-"
            result_tag = "[WIN]" if pnl >= 0 else "[LOSS]"
            lines.append(
                f"- {result_tag} **{p.symbol}** {side} {p.size} x {leverage}x "
                f"| {open_t}→{close_t} | 入{entry:.1f}→出{close:.1f} "
                f"| **{pnl_sign}{pnl:.2f} USDT** | 由 `{agent}` 发起"
            )
        lines.append("")
    else:
        lines.append("今日无已平仓交易。")
        lines.append("")
    
    if open_positions:
        lines.append(f"### 仍持仓中 ({len(open_positions)} 笔)")
        for p in open_positions:
            side = p.side.value.upper() if hasattr(p.side, 'value') else str(p.side).upper()
            agent = p.agent_name or p.source or "manual"
            lines.append(
                f"- {p.symbol} {side} {p.size} × {p.leverage}x "
                f"入场 {float(p.entry_price):.1f} | 由 `{agent}` 发起"
            )
        lines.append("")
    
    # ============ 2. 决策角斗场 ============
    lines.append("---")
    lines.append("## 决策角斗场（AI 辩论精华）")
    lines.append("")
    
    log_result = await db.execute(
        select(HubLog).where(
            HubLog.user_id == current_user.id,
            HubLog.created_at >= day_start,
            HubLog.created_at < day_end,
            HubLog.log_type == "ai_text",
        ).order_by(HubLog.created_at).limit(50)
    )
    logs = log_result.scalars().all()
    
    if logs:
        for lg in logs:
            name = lg.agent_name or "Unknown"
            content = (lg.content or "")[:400]
            time_str = (lg.created_at + timedelta(hours=8)).strftime("%H:%M:%S") if lg.created_at else ""
            lines.append(f"**[{time_str}] {name}:**")
            lines.append(f"> {content}")
            lines.append("")
    else:
        lines.append("今日无 AI 辩论记录。")
        lines.append("")
    
    # ============ 3. 意难平清单 ============
    lines.append("---")
    lines.append("## 意难平清单（被风控拦截的交易申请）")
    lines.append("")
    
    intercept_result = await db.execute(
        select(InterceptedOrder).where(
            InterceptedOrder.user_id == current_user.id,
            InterceptedOrder.created_at >= day_start,
            InterceptedOrder.created_at < day_end,
        ).order_by(InterceptedOrder.created_at)
    )
    intercepted = intercept_result.scalars().all()
    
    if intercepted:
        lines.append(f"今日共 **{len(intercepted)}** 笔交易被风控无情拦截：")
        lines.append("")
        for i, order in enumerate(intercepted, 1):
            time_str = (order.created_at + timedelta(hours=8)).strftime("%H:%M:%S") if order.created_at else ""
            price = float(order.price_at_intercept or 0)
            agent = order.agent_name or "unknown"
            lines.append(
                f"{i}. **[{time_str}]** `{agent}` 想 {order.side.upper()} "
                f"**{order.symbol}** {order.quantity} × {order.leverage}x "
                f"@ {price:.1f}"
            )
            lines.append(f"   - 拦截原因：{order.intercept_reason}")
            if order.verdict:
                verdict_map = {
                    "dodged_bullet": "[幸免于难]",
                    "missed_opportunity": "[踏空了]",
                    "neutral": "[无所谓]",
                }
                lines.append(f"   - 事后裁定：{verdict_map.get(order.verdict, order.verdict)}")
            lines.append("")
    else:
        lines.append("今日无被拦截的交易。风平浪静。")
        lines.append("")
    
    # ============ 尾注 ============
    lines.append("---")
    lines.append('*以上为系统原始数据导出，可直接复制粘贴给 ChatGPT 要求润色成"交易日记"、"复盘战报"等爆款格式。*')
    
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")
