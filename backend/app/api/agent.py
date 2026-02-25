"""
Agent API
==========
AI 浜ゆ槗浠ｇ悊绔偣

绔偣:
    POST /api/agent/conversations           - 鍒涘缓鏂颁細璇?
    GET  /api/agent/conversations           - 鍒楀嚭浼氳瘽
    DELETE /api/agent/conversations/{id}    - 鍒犻櫎浼氳瘽
    POST /api/agent/conversations/{id}/chat - 鍙戞秷鎭?(SSE 娴佸紡)
    GET  /api/agent/conversations/{id}/messages - 鑾峰彇鍘嗗彶娑堟伅
    GET  /api/agent/personas               - 鑾峰彇鍙敤瑙掕壊鍒楄〃
    POST /api/agent/autopilot/start        - 鍚姩鑷姩浜ゆ槗
    POST /api/agent/autopilot/stop         - 鍋滄鑷姩浜ゆ槗
    POST /api/agent/autopilot/run-once     - 鎵嬪姩瑙﹀彂涓€娆?
    GET  /api/agent/autopilot/status       - 鏌ヨ鐘舵€?
"""

import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, delete
from loguru import logger

from app.api.deps import CurrentUser, DbSession
from app.db.session import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent import ChatConversation, ChatMessage
from app.services.agent.agent import chat_stream
from app.services.agent.prompts import get_persona_names
from app.services.agent.autopilot import autopilot


router = APIRouter(tags=["Agent"])


# ==================== Schemas ====================

class CreateConversationRequest(BaseModel):
    """鍒涘缓浼氳瘽璇锋眰"""
    persona: str = Field(default="conservative", description="AI 瑙掕壊 ID")


class ConversationResponse(BaseModel):
    """浼氳瘽鍝嶅簲"""
    id: int
    title: str
    persona: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """鑱婂ぉ璇锋眰"""
    message: str = Field(..., min_length=1, max_length=5000, description="鐢ㄦ埛娑堟伅")


class MessageResponse(BaseModel):
    """娑堟伅鍝嶅簲"""
    id: int
    role: str
    content: str
    tool_name: Optional[str] = None
    tool_result: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class PersonaResponse(BaseModel):
    """瑙掕壊鍝嶅簲"""
    id: str
    name: str


# ==================== Routes ====================

@router.get("/personas", response_model=List[PersonaResponse])
async def list_personas():
    """鑾峰彇鍙敤 AI 瑙掕壊鍒楄〃"""
    return get_persona_names()


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    鍒涘缓鏂颁細璇?

    姣忎釜浼氳瘽鏈夌嫭绔嬬殑 AI 璁板繂鍜岃鑹茶瀹?
    """
    # 楠岃瘉瑙掕壊 ID
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
        created_at=conv.created_at.isoformat() + "Z",
        updated_at=conv.updated_at.isoformat() + "Z",
    )


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    鍒楀嚭鐢ㄦ埛鐨勬墍鏈変細璇?

    鎸夋洿鏂版椂闂村€掑簭鎺掑垪
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
            created_at=c.created_at.isoformat() + "Z",
            updated_at=c.updated_at.isoformat() + "Z",
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
    鍒犻櫎浼氳瘽鍙婂叾鎵€鏈夋秷鎭?
    """
    # 楠岃瘉鎵€灞炴潈
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 鍒犻櫎娑堟伅 (CASCADE 浼氬鐞嗭紝浣嗘樉寮忓垹闄ゆ洿瀹夊叏)
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
    鍙戦€佹秷鎭苟鑾峰彇 AI 鍥炲 (SSE 娴佸紡)

    鍝嶅簲鏍煎紡: Server-Sent Events
    姣忎釜浜嬩欢鏄?JSON 瀵硅薄:
    - {"type": "text", "content": "..."} 鈥?AI 鏂囨湰鐗囨
    - {"type": "tool_call", "tool": "...", "args": {...}} 鈥?宸ュ叿璋冪敤
    - {"type": "tool_result", "tool": "...", "result": "..."} 鈥?宸ュ叿缁撴灉
    - {"type": "done", "full_reply": "..."} 鈥?瀹屾垚
    - {"type": "error", "message": "..."} 鈥?閿欒
    """
    # 楠岃瘉浼氳瘽鎵€灞炴潈
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
    鑾峰彇浼氳瘽鐨勫巻鍙叉秷鎭?

    鎸夋椂闂存搴忔帓鍒?
    """
    # 楠岃瘉浼氳瘽鎵€灞炴潈
    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 鑾峰彇娑堟伅
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
            created_at=m.created_at.isoformat() + "Z",
        )
        for m in messages
    ]


# ==================== Autopilot ====================

class AutopilotStartRequest(BaseModel):
    """鍚姩 autopilot 璇锋眰"""
    symbols: List[str] = Field(default=["BTCUSDT"], description="浜ゆ槗瀵瑰垪琛?)
    interval: str = Field(default="15m", description="鍐崇瓥闂撮殧: 5m/15m/30m/1h/4h")
    intervals: List[str] = Field(default=[], description="澶氱骇鍒寚鏍? [5m, 1h, 4h]")


@router.post("/autopilot/start")
async def autopilot_start(
    request: AutopilotStartRequest,
    current_user: CurrentUser,
):
    """鍚姩鑷姩浜ゆ槗妯″紡"""
    if request.interval not in ("5m", "15m", "30m", "1h", "4h"):
        raise HTTPException(status_code=400, detail="interval 鍙敮鎸?5m/15m/30m/1h/4h")

    await autopilot.start(
        user_id=current_user.id,
        config={
            "symbols": request.symbols,
            "interval": request.interval,
            "intervals": request.intervals if request.intervals else [request.interval],
        },
    )
    return {"message": "Autopilot started", **autopilot.get_status(current_user.id)}


@router.post("/autopilot/stop")
async def autopilot_stop(current_user: CurrentUser):
    """鍋滄鑷姩浜ゆ槗"""
    await autopilot.stop(current_user.id)
    return {"message": "Autopilot stopped"}


@router.post("/autopilot/run-once")
async def autopilot_run_once(
    current_user: CurrentUser,
    symbol: str = Query(default="BTCUSDT", description="浜ゆ槗瀵?),
):
    """鎵嬪姩瑙﹀彂涓€娆?autopilot 鍐崇瓥"""
    reply = await autopilot.run_once(current_user.id, symbol)
    return {"reply": reply}


@router.get("/autopilot/status")
async def autopilot_status(current_user: CurrentUser):
    """鏌ヨ autopilot 鐘舵€?""
    return autopilot.get_status(current_user.id)


@router.get("/autopilot/logs")
async def autopilot_logs(
    current_user: CurrentUser,
    limit: int = Query(default=200, ge=1, le=500, description="杩斿洖鏉℃暟"),
    symbol: Optional[str] = Query(default=None, description="鎸変氦鏄撳杩囨护"),
    since: Optional[str] = Query(default=None, description="鍙繑鍥炴鏃堕棿涔嬪悗鐨勬棩蹇?(ISO鏍煎紡)"),
):
    """鏌ヨ autopilot 鍐崇瓥鏃ュ織"""
    logs = await autopilot.get_logs(
        user_id=current_user.id,
        limit=limit,
        symbol=symbol,
        since=since,
    )
    return logs


@router.delete("/autopilot/logs")
async def autopilot_clear_logs(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """娓呯┖ autopilot 鍐崇瓥鏃ュ織"""
    from app.models.autopilot_log import AutopilotLog
    result = await db.execute(
        AutopilotLog.__table__.delete().where(
            AutopilotLog.user_id == current_user.id
        )
    )
    await db.commit()
    return {"message": f"宸叉竻绌?{result.rowcount} 鏉¤褰?}
