"""
Rate Limiting Middleware
========================
基于 Redis 的请求速率限制

用于防止:
- 暴力破解密码
- API 滥用
- DDoS 攻击
"""

import time
from typing import Optional, Callable
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    速率限制中间件
    
    配置项:
    - requests_per_minute: 每分钟最大请求数
    - burst_size: 突发请求容量
    - exclude_paths: 不限制的路径
    """
    
    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        exclude_paths: Optional[list[str]] = None,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_size = burst_size
        self.exclude_paths = exclude_paths or ["/health", "/", "/docs", "/openapi.json"]
        
        # 内存存储 (生产环境应使用 Redis)
        self._requests: dict[str, list[float]] = {}
        
    def _get_client_ip(self, request: Request) -> str:
        """提取客户端 IP"""
        # 优先从代理头获取真实 IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
    
    def _is_rate_limited(self, client_ip: str) -> bool:
        """检查是否超过速率限制"""
        now = time.time()
        window_start = now - 60  # 1 分钟窗口
        
        # 清理过期记录
        if client_ip in self._requests:
            self._requests[client_ip] = [
                t for t in self._requests[client_ip] if t > window_start
            ]
        else:
            self._requests[client_ip] = []
        
        # 检查是否超限
        if len(self._requests[client_ip]) >= self.requests_per_minute:
            return True
        
        # 记录请求
        self._requests[client_ip].append(now)
        return False
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求"""
        # 检查是否在排除列表
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.exclude_paths):
            return await call_next(request)
        
        # 获取客户端 IP
        client_ip = self._get_client_ip(request)
        
        # 检查速率限制
        if self._is_rate_limited(client_ip):
            logger.warning(f"[RateLimit] IP {client_ip} exceeded rate limit")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": "60"},
            )
        
        return await call_next(request)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """
    基于 Redis 的速率限制 (推荐用于生产环境)
    
    优点:
    - 分布式: 多实例共享限制计数
    - 持久化: 重启不会重置计数
    - 高性能: Redis 原子操作
    """
    
    def __init__(
        self,
        app,
        redis_client,  # aioredis or redis-py async client
        requests_per_minute: int = 60,
        exclude_paths: Optional[list[str]] = None,
    ):
        super().__init__(app)
        self.redis = redis_client
        self.requests_per_minute = requests_per_minute
        self.exclude_paths = exclude_paths or ["/health", "/", "/docs"]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求"""
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.exclude_paths):
            return await call_next(request)
        
        # 获取客户端 IP
        client_ip = self._get_client_ip(request)
        key = f"ratelimit:{client_ip}"
        
        try:
            # 使用 Redis INCR + EXPIRE 实现滑动窗口
            current = await self.redis.incr(key)
            if current == 1:
                await self.redis.expire(key, 60)  # 1 分钟过期
            
            if current > self.requests_per_minute:
                ttl = await self.redis.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(ttl)},
                )
        except HTTPException:
            raise
        except Exception as e:
            # Redis 故障时跳过限制 (fail-open)
            logger.warning(f"[RateLimit] Redis error: {e}")
        
        return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
