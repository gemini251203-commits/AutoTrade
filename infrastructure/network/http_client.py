"""
HTTPClient - 统一 HTTP 客户端
==============================
基于 httpx 的异步 HTTP 客户端，自动应用代理配置。

使用示例:
    from infrastructure.network import NetworkManager
    
    nm = NetworkManager()
    client = nm.get_http_client()
    
    async with client as http:
        response = await http.get("https://api.binance.com/api/v3/ticker/price")
        data = response.json()
"""

import httpx
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager


class HTTPClient:
    """
    统一 HTTP 客户端
    
    特性:
    - 自动代理配置
    - 异步上下文管理器
    - 统一的超时和重试配置
    """
    
    DEFAULT_TIMEOUT = 30.0  # 默认超时时间 (秒)
    DEFAULT_HEADERS = {
        "User-Agent": "AutoTrade/1.0",
        "Accept": "application/json",
    }
    
    def __init__(
        self,
        proxy_config: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        初始化 HTTP 客户端
        
        Args:
            proxy_config: 代理配置字典，如 {"http://": "http://127.0.0.1:7897"}
            timeout: 请求超时时间 (秒)
            headers: 自定义请求头
        """
        self._proxy_config = proxy_config or {}
        self._timeout = httpx.Timeout(timeout)
        self._headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 httpx AsyncClient"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                proxies=self._proxy_config if self._proxy_config else None,
                timeout=self._timeout,
                headers=self._headers,
                follow_redirects=True,
            )
        return self._client
    
    async def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> httpx.Response:
        """
        发送 GET 请求
        
        Args:
            url: 请求 URL
            params: 查询参数
            headers: 额外的请求头
            **kwargs: 传递给 httpx 的其他参数
        
        Returns:
            httpx.Response: 响应对象
        """
        client = await self._get_client()
        return await client.get(url, params=params, headers=headers, **kwargs)
    
    async def post(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> httpx.Response:
        """
        发送 POST 请求
        
        Args:
            url: 请求 URL
            data: 表单数据
            json: JSON 数据
            headers: 额外的请求头
            **kwargs: 传递给 httpx 的其他参数
        
        Returns:
            httpx.Response: 响应对象
        """
        client = await self._get_client()
        return await client.post(url, data=data, json=json, headers=headers, **kwargs)
    
    async def put(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> httpx.Response:
        """发送 PUT 请求"""
        client = await self._get_client()
        return await client.put(url, data=data, json=json, headers=headers, **kwargs)
    
    async def delete(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> httpx.Response:
        """发送 DELETE 请求"""
        client = await self._get_client()
        return await client.delete(url, headers=headers, **kwargs)
    
    async def close(self):
        """关闭客户端连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self) -> "HTTPClient":
        await self._get_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
