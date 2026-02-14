"""
Prometheus-Style Metrics
=========================
轻量级应用指标收集

不依赖 prometheus_client 库，使用纯 Python 实现。
通过 /metrics 端点暴露 JSON 格式指标。

指标:
- 请求计数和延迟 (从 AccessLogger 收集)
- Redis 缓存命中率
- WebSocket 连接数
- 断路器状态
"""

import time
from typing import Optional
from loguru import logger


class MetricsCollector:
    """全局指标收集器 (单例)"""
    
    _instance: Optional["MetricsCollector"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._start_time = time.time()
        
        # 请求统计
        self.total_requests = 0
        self.total_errors = 0  # 4xx + 5xx
        self.slow_requests = 0
        
        # 缓存统计
        self.cache_hits = 0
        self.cache_misses = 0
        
        # WebSocket 统计
        self.ws_connections = 0
        self.ws_messages_sent = 0
    
    def record_request(self, status_code: int, is_slow: bool = False):
        """记录一次 HTTP 请求"""
        self.total_requests += 1
        if status_code >= 400:
            self.total_errors += 1
        if is_slow:
            self.slow_requests += 1
    
    def record_cache_hit(self):
        self.cache_hits += 1
    
    def record_cache_miss(self):
        self.cache_misses += 1
    
    def ws_connect(self):
        self.ws_connections += 1
    
    def ws_disconnect(self):
        self.ws_connections = max(0, self.ws_connections - 1)
    
    def ws_message(self):
        self.ws_messages_sent += 1
    
    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time
    
    @property
    def cache_hit_rate(self) -> str:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return "N/A"
        return f"{self.cache_hits / total * 100:.1f}%"
    
    @property
    def error_rate(self) -> str:
        if self.total_requests == 0:
            return "N/A"
        return f"{self.total_errors / self.total_requests * 100:.1f}%"
    
    def snapshot(self) -> dict:
        """获取当前指标快照"""
        from app.core.circuit_breaker import get_all_circuit_breaker_stats
        
        return {
            "uptime_seconds": round(self.uptime_seconds, 0),
            "requests": {
                "total": self.total_requests,
                "errors": self.total_errors,
                "slow": self.slow_requests,
                "error_rate": self.error_rate,
            },
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": self.cache_hit_rate,
            },
            "websocket": {
                "active_connections": self.ws_connections,
                "messages_sent": self.ws_messages_sent,
            },
            "circuit_breakers": get_all_circuit_breaker_stats(),
        }


# 全局实例
metrics = MetricsCollector()
