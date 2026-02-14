"""
AutoTrade Infrastructure - Network Module
==========================================
统一网络管理器，实现环境无感知的 HTTP/WebSocket 客户端。

核心原则:
- 自动识别 ENV_TYPE (local/prod) 配置代理
- 其他模块严禁私自使用 requests 或 proxies
- 所有外部请求必须通过此模块
"""

from .manager import NetworkManager
from .http_client import HTTPClient
from .ws_client import WebSocketClient

__all__ = ["NetworkManager", "HTTPClient", "WebSocketClient"]
