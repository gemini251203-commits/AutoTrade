"""
User Config API
================
用户配置相关端点

端点:
    GET  /user/ai-config       - 获取用户 AI 配置
    PUT  /user/ai-config       - 更新用户 AI 配置
    POST /user/ai-config/test  - 测试 AI 连接
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.user_ai_config import UserAIConfig, AIProvider
from app.core.encryption import encrypt_api_key, decrypt_api_key, mask_api_key


router = APIRouter(tags=["User Config"])


# ==================== Schemas ====================

class AIConfigResponse(BaseModel):
    """AI 配置响应 (脱敏)"""
    provider: str
    api_base_url: Optional[str] = None
    api_key_masked: Optional[str] = None  # 脱敏后的 key
    api_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    system_prompt: Optional[str] = None
    use_deep_thinking: bool = False  # 深度思考模式
    max_leverage: int = 20
    max_position_percent: float = 50.0
    max_loss_percent: float = 5.0


class AIConfigUpdate(BaseModel):
    """AI 配置更新请求"""
    provider: str = Field(..., pattern="^(ollama|deepseek|openai)$")
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None  # 明文 key，后端加密存储
    api_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    system_prompt: Optional[str] = None
    use_deep_thinking: Optional[bool] = None  # 深度思考模式
    max_leverage: Optional[int] = Field(None, ge=1, le=125)
    max_position_percent: Optional[float] = Field(None, ge=1, le=100)
    max_loss_percent: Optional[float] = Field(None, ge=1, le=50)


class AIConfigTestRequest(BaseModel):
    """测试连接请求"""
    provider: str = Field(..., pattern="^(ollama|deepseek|openai)$")
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class AIConfigTestResponse(BaseModel):
    """测试连接响应"""
    success: bool
    message: str
    model_info: Optional[dict] = None


# ==================== Routes ====================

@router.get("/ai-config", response_model=AIConfigResponse)
async def get_ai_config(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取当前用户的 AI 配置
    
    返回脱敏后的配置信息
    """
    result = await db.execute(
        select(UserAIConfig).where(UserAIConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    
    if not config:
        # 返回默认配置
        return AIConfigResponse(
            provider="ollama",
            ollama_base_url="http://localhost:11434",
            ollama_model="deepseek-r1:14b",
            api_base_url="https://api.deepseek.com",
            api_model="deepseek-chat",
            system_prompt="You are QuantaPro, a professional Crypto Quant Trader.",
            use_deep_thinking=False,
        )
    
    # 解密并脱敏 API Key
    api_key_masked = None
    if config.api_key_encrypted:
        try:
            plain_key = decrypt_api_key(config.api_key_encrypted)
            api_key_masked = mask_api_key(plain_key)
        except Exception:
            api_key_masked = "********"
    
    return AIConfigResponse(
        provider=config.provider.value,
        api_base_url=config.api_base_url,
        api_key_masked=api_key_masked,
        api_model=config.api_model,
        ollama_base_url=config.ollama_base_url,
        ollama_model=config.ollama_model,
        system_prompt=config.system_prompt,
        use_deep_thinking=config.use_deep_thinking,
        max_leverage=config.max_leverage,
        max_position_percent=config.max_position_percent,
        max_loss_percent=config.max_loss_percent,
    )


@router.put("/ai-config", response_model=AIConfigResponse)
async def update_ai_config(
    request: AIConfigUpdate,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    更新用户 AI 配置
    
    API Key 会被加密存储
    """
    # 查找现有配置
    result = await db.execute(
        select(UserAIConfig).where(UserAIConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    
    # 如果不存在则创建
    if not config:
        config = UserAIConfig(user_id=current_user.id)
        db.add(config)
    
    # 更新字段
    config.provider = AIProvider(request.provider)
    
    if request.api_base_url is not None:
        config.api_base_url = request.api_base_url
    
    if request.api_key is not None and request.api_key.strip():
        # 加密存储 API Key
        config.api_key_encrypted = encrypt_api_key(request.api_key.strip())
    
    if request.api_model is not None:
        config.api_model = request.api_model
    
    if request.ollama_base_url is not None:
        config.ollama_base_url = request.ollama_base_url
    
    if request.ollama_model is not None:
        config.ollama_model = request.ollama_model
    
    if request.system_prompt is not None:
        config.system_prompt = request.system_prompt
    
    if request.max_leverage is not None:
        config.max_leverage = request.max_leverage
    
    if request.max_position_percent is not None:
        config.max_position_percent = request.max_position_percent
    
    if request.max_loss_percent is not None:
        config.max_loss_percent = request.max_loss_percent
    
    if request.use_deep_thinking is not None:
        config.use_deep_thinking = request.use_deep_thinking
    
    await db.commit()
    await db.refresh(config)
    
    logger.info(f"[UserConfig] User {current_user.id} updated AI config: provider={request.provider}")
    
    # 返回更新后的配置
    return await get_ai_config(current_user, db)


@router.post("/ai-config/test", response_model=AIConfigTestResponse)
async def test_ai_connection(
    request: AIConfigTestRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """
    测试 AI 连接
    
    验证 API Key 和连接是否有效
    """
    import httpx
    
    try:
        if request.provider == "ollama":
            # 测试 Ollama 连接
            base_url = request.ollama_base_url or "http://localhost:11434"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = [m.get("name") for m in models]
                    return AIConfigTestResponse(
                        success=True,
                        message=f"Ollama 连接成功，发现 {len(models)} 个模型",
                        model_info={"available_models": model_names[:10]},
                    )
                else:
                    return AIConfigTestResponse(
                        success=False,
                        message=f"Ollama 连接失败: HTTP {resp.status_code}",
                    )
        
        elif request.provider in ("deepseek", "openai"):
            # 测试 Cloud API 连接
            base_url = request.api_base_url or "https://api.deepseek.com"
            api_key = request.api_key
            
            if not api_key:
                # 尝试从数据库获取
                result = await db.execute(
                    select(UserAIConfig).where(UserAIConfig.user_id == current_user.id)
                )
                config = result.scalar_one_or_none()
                if config and config.api_key_encrypted:
                    api_key = decrypt_api_key(config.api_key_encrypted)
            
            if not api_key:
                return AIConfigTestResponse(
                    success=False,
                    message="请提供 API Key",
                )
            
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    model_names = [m.get("id") for m in models]
                    return AIConfigTestResponse(
                        success=True,
                        message=f"API 连接成功，发现 {len(models)} 个模型",
                        model_info={"available_models": model_names[:10]},
                    )
                elif resp.status_code == 401:
                    return AIConfigTestResponse(
                        success=False,
                        message="API Key 无效或已过期",
                    )
                else:
                    return AIConfigTestResponse(
                        success=False,
                        message=f"API 连接失败: HTTP {resp.status_code}",
                    )
        
        else:
            return AIConfigTestResponse(
                success=False,
                message=f"不支持的 provider: {request.provider}",
            )
    
    except httpx.ConnectError:
        return AIConfigTestResponse(
            success=False,
            message="连接失败，请检查网络或服务地址",
        )
    except Exception as e:
        logger.error(f"[AITest] Connection test failed: {e}")
        return AIConfigTestResponse(
            success=False,
            message=f"测试失败: {str(e)}",
        )
