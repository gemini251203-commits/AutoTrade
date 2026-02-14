"""
AI API
=======
AI 分析和聊天相关端点

端点:
    POST /ai/chat           - AI 对话
    POST /ai/parse-signal   - 解析喊单信号
    POST /ai/analyze/{sym}  - 分析交易对
    GET  /ai/context/{sym}  - 获取 AI 上下文
"""

from typing import List, Optional, Any
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from loguru import logger

from app.api.deps import CurrentUser, DbSession
from app.services.ai import AIBrain


router = APIRouter()


# ==================== Schemas ====================

class ChatMessage(BaseModel):
    """聊天消息"""
    role: str  # user/assistant
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    messages: List[ChatMessage]
    symbol: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应"""
    message: str
    signal: Optional[dict] = None


class ParseSignalRequest(BaseModel):
    """信号解析请求"""
    text: str = Field(..., min_length=1, max_length=2000, description="喊单文本")
    symbol: Optional[str] = Field(None, description="可选指定币种")


class ParsedSignalResponse(BaseModel):
    """解析后的信号响应"""
    success: bool
    signal: Optional[dict] = None
    context: Optional[dict] = None
    error: Optional[str] = None


class AIContextResponse(BaseModel):
    """AI 上下文响应"""
    market: Optional[dict] = None
    wallet: Optional[dict] = None
    positions: List[dict] = []
    pending_orders: int = 0
    running_grids: int = 0
    timestamp: str = ""


# ==================== Routes ====================

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    AI 对话接口
    
    使用用户配置的 AI 进行对话
    """
    try:
        from app.services.ai.providers import ChatMessage as ProviderMessage

        # 获取 provider
        provider = await AIBrain.get_provider(db, current_user.id)
        
        # 转换消息格式
        messages = [
            ProviderMessage(role=m.role, content=m.content)
            for m in request.messages
        ]
        
        # 调用 AI
        response = await provider.chat(messages)
        
        return ChatResponse(
            message=response.content,
            signal=None,
        )
    
    except Exception as e:
        logger.error(f"[AI Chat] Error: {e}")
        return ChatResponse(
            message=f"AI 服务错误: {str(e)}",
            signal=None,
        )


@router.post("/parse-signal", response_model=ParsedSignalResponse)
async def parse_signal(
    request: ParseSignalRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    解析喊单信号
    
    将用户的喊单文本解析为结构化的交易参数
    
    示例输入:
    - "BTC多 入场78000-78500 止损77000 止盈82000 5倍杠杆"
    - "ETH 做空 当前价 止损+3% 止盈-10%"
    - "SOL 网格 50-80 20格 500U"
    
    返回:
    - 结构化的交易参数
    - AI 分析推理
    - 风险提示
    """
    try:
        # 调用 AIBrain 解析
        signal = await AIBrain.parse_signal(
            db=db,
            user_id=current_user.id,
            text=request.text,
            symbol=request.symbol,
        )
        
        # 同时返回上下文信息
        context = await AIBrain.build_context(
            db=db,
            user_id=current_user.id,
            symbol=signal.symbol,
        )
        
        return ParsedSignalResponse(
            success=True,
            signal=asdict(signal),
            context={
                "market": asdict(context.market) if context.market else None,
                "wallet": asdict(context.wallet) if context.wallet else None,
                "positions_count": len(context.positions),
                "pending_orders": context.pending_orders,
                "running_grids": context.running_grids,
            },
        )
    
    except ValueError as e:
        return ParsedSignalResponse(
            success=False,
            error=str(e),
        )
    except Exception as e:
        logger.error(f"[AI ParseSignal] Error: {e}")
        return ParsedSignalResponse(
            success=False,
            error=f"解析失败: {str(e)}",
        )


@router.get("/context/{symbol}", response_model=AIContextResponse)
async def get_ai_context(
    symbol: str,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取 AI 上下文
    
    返回当前市场、钱包、持仓等信息
    """
    try:
        context = await AIBrain.build_context(
            db=db,
            user_id=current_user.id,
            symbol=symbol.upper(),
        )
        
        return AIContextResponse(
            market=asdict(context.market) if context.market else None,
            wallet=asdict(context.wallet) if context.wallet else None,
            positions=[asdict(p) for p in context.positions],
            pending_orders=context.pending_orders,
            running_grids=context.running_grids,
            timestamp=context.timestamp,
        )
    
    except Exception as e:
        logger.error(f"[AI Context] Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/analyze/{symbol}")
async def analyze_symbol(
    symbol: str,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    AI 分析指定交易对
    
    综合技术分析和 AI 建议
    """
    try:
        # 获取上下文
        context = await AIBrain.build_context(
            db=db,
            user_id=current_user.id,
            symbol=symbol.upper(),
        )
        
        # 使用 AIBrain 解析一个简单的分析请求
        signal = await AIBrain.parse_signal(
            db=db,
            user_id=current_user.id,
            text=f"分析 {symbol} 的走势，给出交易建议",
            symbol=symbol.upper(),
        )
        
        return {
            "symbol": symbol.upper(),
            "current_price": context.market.current_price if context.market else 0,
            "analysis": signal.reasoning,
            "signal": {
                "side": signal.side,
                "entry_low": signal.entry_low,
                "entry_high": signal.entry_high,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "confidence": signal.confidence,
            },
            "warnings": signal.warnings,
        }
    
    except Exception as e:
        logger.error(f"[AI Analyze] Error: {e}")
        return {
            "symbol": symbol,
            "analysis": f"分析失败: {str(e)}",
            "signal": None,
        }


@router.post("/multi-analyze/{symbol}")
async def multi_analyze_symbol(
    symbol: str,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    多智能体分析
    
    调用 3 个 AI 分析师（技术/情绪/风控）并行分析，
    由决策者汇总输出最终建议。
    """
    from app.core.config import settings
    
    try:
        if settings.multi_agent_enabled:
            result = await AIBrain.multi_analyze(
                db=db,
                user_id=current_user.id,
                symbol=symbol.upper(),
            )
            return result
        else:
            return await analyze_symbol(symbol, current_user, db)
    
    except Exception as e:
        logger.error(f"[Multi-Agent Analyze] Error: {e}")
        return {
            "symbol": symbol.upper(),
            "final_recommendation": "neutral",
            "confidence": 0.0,
            "final_decision": f"分析失败: {str(e)}",
            "reasoning": "",
            "warnings": [str(e)],
            "reports": [],
        }
