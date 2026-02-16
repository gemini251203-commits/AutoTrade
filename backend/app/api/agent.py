"""
Agent API
==========
AI 交易代理端点

端点:
    POST /api/agent/conversations           - 创建新会话
    GET  /api/agent/conversations           - 列出会话
    DELETE /api/agent/conversations/{id}    - 删除会话
    POST /api/agent/conversations/{id}/chat - 发消息 (SSE 流式)
    GET  /api/agent/conversations/{id}/messages - 获取历史消息
    GET  /api/agent/personas               - 获取可用角色列表
    POST /api/agent/autopilot/start        - 启动自动交易
    POST /api/agent/autopilot/stop         - 停止自动交易
    POST /api/agent/autopilot/run-once     - 手动触发一次
    GET  /api/agent/autopilot/status       - 查询状态
"""

import json
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, delete
from loguru import logger

from app.api.deps import CurrentUser, DbSession
from app.models.agent import ChatConversation, ChatMessage
from app.services.agent.agent import chat_stream
from app.services.agent.prompts import get_persona_names
from app.services.agent.autopilot import autopilot


router = APIRouter(tags=["Agent"])


# ==================== Schemas ====================

class CreateConversationRequest(BaseModel):
    """创建会话请求"""
    persona: str = Field(default="conservative", description="AI 角色 ID")


class ConversationResponse(BaseModel):
    """会话响应"""
    id: int
    title: str
    persona: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(..., min_length=1, max_length=5000, description="用户消息")


class MessageResponse(BaseModel):
    """消息响应"""
    id: int
    role: str
    content: str
    tool_name: Optional[str] = None
    tool_result: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class PersonaResponse(BaseModel):
    """角色响应"""
    id: str
    name: str


# ==================== Routes ====================

@router.get("/personas", response_model=List[PersonaResponse])
async def list_personas():
    """获取可用 AI 角色列表"""
    return get_persona_names()


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    创建新会话

    每个会话有独立的 AI 记忆和角色设定
    """
    # 验证角色 ID
    valid_personas = [p["id"] for p in get_persona_names()]
    if request.persona not in valid_personas:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid persona: {request.persona}. Valid: {valid_personas}",
        )

    conv = ChatConversation(
        user_id=current_user.id,
        persona=request.persona,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        persona=conv.persona,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    列出用户的所有会话

    按更新时间倒序排列
    """
    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.user_id == current_user.id)
        .order_by(desc(ChatConversation.updated_at))
    )
    conversations = result.scalars().all()

    return [
        ConversationResponse(
            id=c.id,
            title=c.title,
            persona=c.persona,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in conversations
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    删除会话及其所有消息
    """
    # 验证所属权
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 删除消息 (CASCADE 会处理，但显式删除更安全)
    await db.execute(
        delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    )
    await db.delete(conv)
    await db.commit()

    return {"message": "Conversation deleted"}


@router.post("/conversations/{conversation_id}/chat")
async def chat(
    conversation_id: int,
    request: ChatRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    发送消息并获取 AI 回复 (SSE 流式)

    响应格式: Server-Sent Events
    每个事件是 JSON 对象:
    - {"type": "text", "content": "..."} — AI 文本片段
    - {"type": "tool_call", "tool": "...", "args": {...}} — 工具调用
    - {"type": "tool_result", "tool": "...", "result": "..."} — 工具结果
    - {"type": "done", "full_reply": "..."} — 完成
    - {"type": "error", "message": "..."} — 错误
    """
    # 验证会话所属权
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        async for event in chat_stream(
            db=db,
            user_id=current_user.id,
            conversation_id=conversation_id,
            user_message=request.message,
            persona=conv.persona,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=List[MessageResponse],
)
async def get_messages(
    conversation_id: int,
    current_user: CurrentUser,
    db: DbSession,
    limit: int = 50,
):
    """
    获取会话的历史消息

    按时间正序排列
    """
    # 验证会话所属权
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 获取消息
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
        .limit(limit)
    )
    messages = result.scalars().all()

    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_name=m.tool_name,
            tool_result=m.tool_result,
            created_at=m.created_at.isoformat(),
        )
        for m in messages
    ]


# ==================== Autopilot ====================

class AutopilotStartRequest(BaseModel):
    """启动 autopilot 请求"""
    symbols: List[str] = Field(default=["BTCUSDT"], description="交易对列表")
    interval: str = Field(default="15m", description="决策间隔: 5m/15m/30m/1h/4h")


@router.post("/autopilot/start")
async def autopilot_start(
    request: AutopilotStartRequest,
    current_user: CurrentUser,
):
    """启动自动交易模式"""
    if request.interval not in ("5m", "15m", "30m", "1h", "4h"):
        raise HTTPException(status_code=400, detail="interval 只支持 5m/15m/30m/1h/4h")

    await autopilot.start(
        user_id=current_user.id,
        config={
            "symbols": request.symbols,
            "interval": request.interval,
        },
    )
    return {"message": "Autopilot started", **autopilot.get_status(current_user.id)}


@router.post("/autopilot/stop")
async def autopilot_stop(current_user: CurrentUser):
    """停止自动交易"""
    await autopilot.stop(current_user.id)
    return {"message": "Autopilot stopped"}


@router.post("/autopilot/run-once")
async def autopilot_run_once(
    current_user: CurrentUser,
    symbol: str = Query(default="BTCUSDT", description="交易对"),
):
    """手动触发一次 autopilot 决策"""
    reply = await autopilot.run_once(current_user.id, symbol)
    return {"reply": reply}


@router.get("/autopilot/status")
async def autopilot_status(current_user: CurrentUser):
    """查询 autopilot 状态"""
    return autopilot.get_status(current_user.id)


@router.get("/autopilot/logs")
async def autopilot_logs(
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
    symbol: Optional[str] = Query(default=None, description="按交易对过滤"),
    since: Optional[str] = Query(default=None, description="只返回此时间之后的日志 (ISO格式)"),
):
    """查询 autopilot 决策日志"""
    logs = await autopilot.get_logs(
        user_id=current_user.id,
        limit=limit,
        symbol=symbol,
        since=since,
    )
    return logs

