"""
NetworkManager - 统一网络适配器
================================
根据 .env 配置自动决定是"直连"还是"走代理"。

使用示例:
    from app.core.network import net_manager
    
    async with net_manager.get_client() as client:
        response = await client.get("https://api.binance.com/api/v3/ping")
"""

import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
import httpx
from loguru import logger


class NetworkManager:
    """
    网络管理器 - 单例模式
    
    职责:
    1. 加载 .env 配置
    2. 根据 USE_PROXY 决定代理模式
    3. 提供统一的 httpx.AsyncClient
    """
    
    _instance: Optional["NetworkManager"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "NetworkManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 加载 .env 文件
        self._load_env()
        
        # 读取代理配置
        self._use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        self._proxy_url = os.getenv("PROXY_URL", "")
        
        # 配置代理
        if self._use_proxy and self._proxy_url:
            self._proxy = self._proxy_url
            logger.info(f"🔌 代理模式已启用: {self._proxy_url}")
        else:
            self._proxy = None
            logger.info("🌐 直连模式 (无代理)")
        
        self._initialized = True
    
    def _load_env(self) -> None:
        """加载 .env 文件"""
        # 尝试多个可能的 .env 路径
        possible_paths = [
            Path(__file__).parent.parent.parent.parent / ".env",  # backend/../.env
            Path.cwd() / ".env",
            Path.cwd().parent / ".env",
        ]
        
        for env_path in possible_paths:
            if env_path.exists():
                load_dotenv(env_path)
                logger.debug(f"Loaded .env from: {env_path}")
                return
        
        logger.warning("No .env file found, using system environment variables")
    
    @property
    def use_proxy(self) -> bool:
        """是否使用代理"""
        return self._use_proxy
    
    @property
    def proxy_url(self) -> str:
        """代理 URL"""
        return self._proxy_url
    
    def get_client(
        self,
        timeout: float = 30.0,
        **kwargs,
    ) -> httpx.AsyncClient:
        """
        获取配置好的 httpx.AsyncClient
        
        Args:
            timeout: 超时时间 (秒)，默认 30 秒
            **kwargs: 传递给 httpx.AsyncClient 的其他参数
        
        Returns:
            httpx.AsyncClient: 已配置代理的异步 HTTP 客户端
        
        使用示例:
            async with net_manager.get_client() as client:
                response = await client.get("https://example.com")
        """
        return httpx.AsyncClient(
            proxy=self._proxy,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={
                "User-Agent": "AutoTrade/1.0",
                "Accept": "application/json",
            },
            **kwargs,
        )
    
    def get_sync_client(
        self,
        timeout: float = 30.0,
        **kwargs,
    ) -> httpx.Client:
        """
        获取同步 HTTP 客户端 (用于测试)
        
        Args:
            timeout: 超时时间 (秒)
            **kwargs: 传递给 httpx.Client 的其他参数
        
        Returns:
            httpx.Client: 已配置代理的同步 HTTP 客户端
        """
        return httpx.Client(
            proxy=self._proxy,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            headers={
                "User-Agent": "AutoTrade/1.0",
                "Accept": "application/json",
            },
            **kwargs,
        )
    
    def __repr__(self) -> str:
        mode = "代理模式" if self._use_proxy else "直连模式"
        return f"<NetworkManager mode={mode}>"


# 全局单例实例
net_manager = NetworkManager()
