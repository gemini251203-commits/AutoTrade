"""
NetworkManager - 统一网络适配器
================================
根据 ENV_TYPE 自动配置代理，提供单例模式的网络客户端。

使用示例:
    from infrastructure.network import NetworkManager
    
    nm = NetworkManager()
    client = nm.get_http_client()
    response = await client.get("https://api.binance.com/api/v3/ping")
"""

import os
from typing import Optional
from functools import lru_cache


class NetworkManager:
    """
    网络管理器 - 单例模式
    
    职责:
    1. 读取 ENV_TYPE 环境变量
    2. 根据环境自动配置代理
    3. 提供统一的 HTTP/WebSocket 客户端
    """
    
    _instance: Optional["NetworkManager"] = None
    
    def __new__(cls) -> "NetworkManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._env_type = os.getenv("ENV_TYPE", "local").lower()
        self._http_proxy = os.getenv("HTTP_PROXY", "")
        self._https_proxy = os.getenv("HTTPS_PROXY", "")
        
        # 生产环境下清空代理配置
        if self._env_type == "prod":
            self._http_proxy = ""
            self._https_proxy = ""
        
        self._initialized = True
    
    @property
    def env_type(self) -> str:
        """当前环境类型: local 或 prod"""
        return self._env_type
    
    @property
    def is_local(self) -> bool:
        """是否为本地开发环境"""
        return self._env_type == "local"
    
    @property
    def is_prod(self) -> bool:
        """是否为生产环境"""
        return self._env_type == "prod"
    
    @property
    def proxy_config(self) -> dict:
        """
        获取代理配置字典
        
        Returns:
            dict: 代理配置，生产环境返回空字典
        """
        if self.is_prod:
            return {}
        
        config = {}
        if self._http_proxy:
            config["http://"] = self._http_proxy
        if self._https_proxy:
            config["https://"] = self._https_proxy
        return config
    
    def get_http_client(self) -> "HTTPClient":
        """
        获取配置好代理的 HTTP 客户端
        
        Returns:
            HTTPClient: 已配置代理的 HTTP 客户端实例
        """
        from .http_client import HTTPClient
        return HTTPClient(proxy_config=self.proxy_config)
    
    def get_ws_client(self) -> "WebSocketClient":
        """
        获取配置好代理的 WebSocket 客户端
        
        Returns:
            WebSocketClient: 已配置代理的 WebSocket 客户端实例
        """
        from .ws_client import WebSocketClient
        return WebSocketClient(proxy_config=self.proxy_config)
    
    def __repr__(self) -> str:
        proxy_status = "enabled" if self.proxy_config else "disabled"
        return f"<NetworkManager env={self._env_type} proxy={proxy_status}>"


@lru_cache(maxsize=1)
def get_network_manager() -> NetworkManager:
    """
    获取 NetworkManager 单例 (带缓存)
    
    这是推荐的获取方式，用于依赖注入。
    """
    return NetworkManager()
