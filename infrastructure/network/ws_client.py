"""
WebSocketClient - 统一 WebSocket 客户端
========================================
基于 websockets 的异步 WebSocket 客户端，自动应用代理配置。

使用示例:
    from infrastructure.network import NetworkManager
    
    nm = NetworkManager()
    ws_client = nm.get_ws_client()
    
    async for message in ws_client.connect("wss://stream.binance.com:9443/ws/btcusdt@ticker"):
        print(message)
"""

import asyncio
import json
import websockets
from typing import Any, AsyncIterator, Callable, Dict, Optional
from websockets.client import WebSocketClientProtocol

try:
    from python_socks.async_.asyncio import Proxy
    from python_socks import ProxyType
    PROXY_SUPPORT = True
except ImportError:
    PROXY_SUPPORT = False


class WebSocketClient:
    """
    统一 WebSocket 客户端
    
    特性:
    - 自动代理配置 (需要 python-socks 库)
    - 自动重连机制
    - 心跳保活
    - 消息回调处理
    """
    
    DEFAULT_PING_INTERVAL = 20  # 心跳间隔 (秒)
    DEFAULT_PING_TIMEOUT = 10   # 心跳超时 (秒)
    DEFAULT_CLOSE_TIMEOUT = 5   # 关闭超时 (秒)
    MAX_RECONNECT_ATTEMPTS = 5  # 最大重连次数
    RECONNECT_DELAY = 5         # 重连延迟 (秒)
    
    def __init__(
        self,
        proxy_config: Optional[Dict[str, str]] = None,
        ping_interval: int = DEFAULT_PING_INTERVAL,
        ping_timeout: int = DEFAULT_PING_TIMEOUT,
    ):
        """
        初始化 WebSocket 客户端
        
        Args:
            proxy_config: 代理配置字典
            ping_interval: 心跳间隔 (秒)
            ping_timeout: 心跳超时 (秒)
        """
        self._proxy_config = proxy_config or {}
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._connection: Optional[WebSocketClientProtocol] = None
        self._running = False
    
    def _get_proxy(self) -> Optional["Proxy"]:
        """
        从代理配置创建 Proxy 对象
        
        Returns:
            Proxy 对象或 None
        """
        if not PROXY_SUPPORT or not self._proxy_config:
            return None
        
        # 优先使用 https 代理
        proxy_url = self._proxy_config.get("https://") or self._proxy_config.get("http://")
        if not proxy_url:
            return None
        
        # 解析代理 URL
        # 格式: http://host:port 或 http://user:pass@host:port
        if proxy_url.startswith("http://"):
            proxy_url = proxy_url[7:]
        elif proxy_url.startswith("https://"):
            proxy_url = proxy_url[8:]
        
        if "@" in proxy_url:
            auth, host_port = proxy_url.rsplit("@", 1)
            username, password = auth.split(":", 1)
        else:
            host_port = proxy_url
            username, password = None, None
        
        host, port = host_port.split(":", 1)
        
        return Proxy(
            proxy_type=ProxyType.HTTP,
            host=host,
            port=int(port),
            username=username,
            password=password,
        )
    
    async def connect(
        self,
        url: str,
        on_message: Optional[Callable[[str], None]] = None,
        auto_reconnect: bool = True,
    ) -> AsyncIterator[str]:
        """
        连接到 WebSocket 并迭代接收消息
        
        Args:
            url: WebSocket URL
            on_message: 消息回调函数 (可选)
            auto_reconnect: 是否自动重连
        
        Yields:
            str: 接收到的消息
        """
        self._running = True
        reconnect_attempts = 0
        
        while self._running:
            try:
                # 构建连接参数
                connect_kwargs = {
                    "ping_interval": self._ping_interval,
                    "ping_timeout": self._ping_timeout,
                    "close_timeout": self.DEFAULT_CLOSE_TIMEOUT,
                }
                
                # 如果有代理支持且配置了代理，创建代理连接
                proxy = self._get_proxy()
                if proxy and PROXY_SUPPORT:
                    sock = await proxy.connect(
                        dest_host=self._extract_host(url),
                        dest_port=self._extract_port(url),
                    )
                    connect_kwargs["sock"] = sock
                
                async with websockets.connect(url, **connect_kwargs) as ws:
                    self._connection = ws
                    reconnect_attempts = 0  # 连接成功，重置重连计数
                    
                    async for message in ws:
                        if on_message:
                            on_message(message)
                        yield message
                        
            except websockets.exceptions.ConnectionClosed as e:
                if not auto_reconnect or not self._running:
                    break
                reconnect_attempts += 1
                if reconnect_attempts > self.MAX_RECONNECT_ATTEMPTS:
                    raise ConnectionError(
                        f"Max reconnection attempts ({self.MAX_RECONNECT_ATTEMPTS}) exceeded"
                    ) from e
                await asyncio.sleep(self.RECONNECT_DELAY)
                
            except Exception as e:
                if not auto_reconnect or not self._running:
                    raise
                reconnect_attempts += 1
                if reconnect_attempts > self.MAX_RECONNECT_ATTEMPTS:
                    raise
                await asyncio.sleep(self.RECONNECT_DELAY)
    
    async def send(self, message: Any) -> None:
        """
        发送消息
        
        Args:
            message: 要发送的消息 (字符串或可 JSON 序列化的对象)
        """
        if not self._connection:
            raise RuntimeError("WebSocket not connected")
        
        if isinstance(message, str):
            await self._connection.send(message)
        else:
            await self._connection.send(json.dumps(message))
    
    async def close(self) -> None:
        """关闭 WebSocket 连接"""
        self._running = False
        if self._connection:
            await self._connection.close()
            self._connection = None
    
    @staticmethod
    def _extract_host(url: str) -> str:
        """从 URL 中提取主机名"""
        # wss://stream.binance.com:9443/ws -> stream.binance.com
        url = url.replace("wss://", "").replace("ws://", "")
        host = url.split("/")[0]
        if ":" in host:
            host = host.split(":")[0]
        return host
    
    @staticmethod
    def _extract_port(url: str) -> int:
        """从 URL 中提取端口"""
        is_secure = url.startswith("wss://")
        url = url.replace("wss://", "").replace("ws://", "")
        host_port = url.split("/")[0]
        if ":" in host_port:
            return int(host_port.split(":")[1])
        return 443 if is_secure else 80
