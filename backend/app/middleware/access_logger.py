"""
Access Logger Middleware
=========================
API 请求日志中间件

功能:
1. 记录每个 API 请求的方法、路径、状态码、耗时
2. 排除高频轮询路径（减少日志噪音）
3. 慢请求标记（> 1s）
4. 错误请求详细记录

日志格式:
    [AccessLog] POST /api/order/ 201 45ms | user=3 ip=1.2.3.4
    [AccessLog] ⚠️ SLOW GET /api/ai/analyze/BTCUSDT 200 3200ms | user=1
"""

import time
from typing import Optional, Callable, Set
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger


class AccessLoggerMiddleware(BaseHTTPMiddleware):
    """
    API 访问日志中间件
    
    配置:
    - exclude_paths: 不记录的路径前缀
    - slow_threshold_ms: 慢请求阈值 (毫秒)
    """
    
    def __init__(
        self,
        app,
        exclude_paths: Optional[list[str]] = None,
        slow_threshold_ms: int = 1000,
    ):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/health",
            "/",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
        self.slow_threshold_ms = slow_threshold_ms
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """记录请求日志"""
        path = request.url.path
        
        # 跳过排除路径
        if any(path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)
        
        # 记录开始时间
        start = time.perf_counter()
        
        # 提取用户信息 (从 Authorization header 解析)
        user_info = self._extract_user_hint(request)
        client_ip = self._get_client_ip(request)
        
        # 执行请求
        response: Response
        try:
            response = await call_next(request)
        except Exception as e:
            # 请求处理异常
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                f"[AccessLog] ❌ {request.method} {path} ERROR {elapsed_ms:.0f}ms "
                f"| {user_info} ip={client_ip} | {type(e).__name__}: {e}"
            )
            raise
        
        # 计算耗时
        elapsed_ms = (time.perf_counter() - start) * 1000
        status_code = response.status_code
        
        # 📊 记录指标
        from app.core.metrics import metrics as app_metrics
        app_metrics.record_request(status_code, is_slow=(elapsed_ms >= self.slow_threshold_ms))
        
        # 构建日志
        if elapsed_ms >= self.slow_threshold_ms:
            # 慢请求
            logger.warning(
                f"[AccessLog] ⚠️ SLOW {request.method} {path} "
                f"{status_code} {elapsed_ms:.0f}ms | {user_info} ip={client_ip}"
            )
        elif status_code >= 500:
            # 服务器错误
            logger.error(
                f"[AccessLog] ❌ {request.method} {path} "
                f"{status_code} {elapsed_ms:.0f}ms | {user_info} ip={client_ip}"
            )
        elif status_code >= 400:
            # 客户端错误 (不含 401/404 频繁的请求)
            logger.info(
                f"[AccessLog] {request.method} {path} "
                f"{status_code} {elapsed_ms:.0f}ms | {user_info} ip={client_ip}"
            )
        else:
            # 正常请求 - 使用 DEBUG 级别避免日志爆炸
            logger.debug(
                f"[AccessLog] {request.method} {path} "
                f"{status_code} {elapsed_ms:.0f}ms | {user_info} ip={client_ip}"
            )
        
        return response
    
    def _extract_user_hint(self, request: Request) -> str:
        """提取用户标识 (不解码 JWT，仅做标记)"""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            # 有 token，标记为已认证用户
            return "user=authenticated"
        return "user=anonymous"
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端 IP"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"
