"""
AI Providers
=============
AI 服务提供商适配器

支持:
- DeepSeek API (Cloud)
- OpenAI API (Cloud)
- Ollama (Local)
"""

import json
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # system/user/assistant
    content: str


@dataclass
class ChatResponse:
    """聊天响应"""
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None
    raw_response: Optional[Dict] = None


class BaseProvider(ABC):
    """AI 提供商基类"""
    
    @abstractmethod
    async def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> ChatResponse:
        """发送聊天请求"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass


class DeepSeekProvider(BaseProvider):
    """
    DeepSeek API 适配器
    
    也兼容 OpenAI API 格式
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
    
    async def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> ChatResponse:
        """
        发送聊天请求
        
        使用 OpenAI 兼容格式
        """
        use_model = model or self.model
        
        # 构建请求体
        payload = {
            "model": use_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                
                if resp.status_code != 200:
                    error_text = resp.text
                    logger.error(f"[DeepSeek] API error {resp.status_code}: {error_text}")
                    raise Exception(f"DeepSeek API error: {resp.status_code}")
                
                data = resp.json()
                
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage")
                
                return ChatResponse(
                    content=content,
                    model=use_model,
                    usage=usage,
                    raw_response=data,
                )
        
        except httpx.TimeoutException:
            logger.error("[DeepSeek] Request timeout")
            raise Exception("DeepSeek API timeout")
        except Exception as e:
            logger.error(f"[DeepSeek] Request failed: {e}")
            raise
    
    async def health_check(self) -> bool:
        """检查 API 连接"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False


class OllamaProvider(BaseProvider):
    """
    Ollama 本地 LLM 适配器
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "deepseek-r1:14b",
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
    
    async def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> ChatResponse:
        """
        发送聊天请求
        
        使用 Ollama 原生 API
        """
        use_model = model or self.model
        
        # 构建请求体
        payload = {
            "model": use_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                
                if resp.status_code != 200:
                    error_text = resp.text
                    logger.error(f"[Ollama] API error {resp.status_code}: {error_text}")
                    raise Exception(f"Ollama API error: {resp.status_code}")
                
                data = resp.json()
                
                content = data.get("message", {}).get("content", "")
                
                return ChatResponse(
                    content=content,
                    model=use_model,
                    usage={
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0),
                    },
                    raw_response=data,
                )
        
        except httpx.TimeoutException:
            logger.error("[Ollama] Request timeout")
            raise Exception("Ollama request timeout")
        except httpx.ConnectError:
            logger.error("[Ollama] Connection failed - is Ollama running?")
            raise Exception("Ollama connection failed")
        except Exception as e:
            logger.error(f"[Ollama] Request failed: {e}")
            raise
    
    async def health_check(self) -> bool:
        """检查 Ollama 连接"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
    
    async def list_models(self) -> List[str]:
        """列出可用模型"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    return [m.get("name") for m in data.get("models", [])]
        except Exception:
            pass
        return []
