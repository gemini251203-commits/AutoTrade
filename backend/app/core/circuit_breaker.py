"""
Circuit Breaker Pattern
========================
保护外部 API 调用 (Binance 等)

功能:
1. 自动检测连续失败
2. 超过阈值后 "断路" — 直接返回失败，不再调用
3. 半开状态定期尝试恢复
4. 记录成功率统计

状态机:
    CLOSED  → (连续 N 次失败) → OPEN
    OPEN    → (等待 reset_timeout) → HALF_OPEN
    HALF_OPEN → (1 次成功) → CLOSED
    HALF_OPEN → (1 次失败) → OPEN

使用方式:
    from app.core.circuit_breaker import circuit_breaker
    
    @circuit_breaker("binance_klines")
    async def get_klines():
        ...
"""

import asyncio
import time
from enum import Enum
from typing import Optional, Callable, Any
from functools import wraps
from loguru import logger


class CircuitState(str, Enum):
    CLOSED = "closed"        # 正常 — 允许请求通过
    OPEN = "open"            # 断路 — 拒绝请求
    HALF_OPEN = "half_open"  # 半开 — 试探性放行


class CircuitBreakerError(Exception):
    """断路器打开时抛出"""
    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is OPEN. Retry after {retry_after:.0f}s"
        )


class CircuitBreakerInstance:
    """
    单个断路器实例
    
    每个外部服务/端点应使用独立的断路器。
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls
        
        # 状态
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0
        
        # 统计
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """当前状态 (含自动转换)"""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(
                    f"[CircuitBreaker] '{self.name}' → HALF_OPEN "
                    f"(after {elapsed:.0f}s cooldown)"
                )
        return self._state
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过断路器调用函数
        
        Raises:
            CircuitBreakerError: 断路器打开时
        """
        async with self._lock:
            current_state = self.state
            self._total_calls += 1
            
            if current_state == CircuitState.OPEN:
                retry_after = self.reset_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise CircuitBreakerError(self.name, max(0, retry_after))
            
            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerError(self.name, 5.0)
                self._half_open_calls += 1
        
        # 在锁外执行实际调用
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure(e)
            raise
    
    async def _on_success(self):
        """调用成功"""
        async with self._lock:
            self._total_successes += 1
            self._failure_count = 0
            self._success_count += 1
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info(
                    f"[CircuitBreaker] '{self.name}' → CLOSED (recovered)"
                )
    
    async def _on_failure(self, error: Exception):
        """调用失败"""
        async with self._lock:
            self._total_failures += 1
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"[CircuitBreaker] '{self.name}' → OPEN "
                    f"(half-open probe failed: {error})"
                )
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"[CircuitBreaker] '{self.name}' → OPEN "
                    f"({self._failure_count} consecutive failures, "
                    f"retry in {self.reset_timeout}s)"
                )
    
    @property
    def stats(self) -> dict:
        """统计信息"""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "success_rate": (
                f"{self._total_successes / self._total_calls * 100:.1f}%"
                if self._total_calls > 0 else "N/A"
            ),
        }


class CircuitBreakerRegistry:
    """
    断路器注册表 (全局管理所有断路器)
    """
    
    def __init__(self):
        self._breakers: dict[str, CircuitBreakerInstance] = {}
    
    def get(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
    ) -> CircuitBreakerInstance:
        """获取或创建断路器"""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreakerInstance(
                name=name,
                failure_threshold=failure_threshold,
                reset_timeout=reset_timeout,
            )
        return self._breakers[name]
    
    def all_stats(self) -> list[dict]:
        """所有断路器的统计"""
        return [cb.stats for cb in self._breakers.values()]


# 全局注册表
_registry = CircuitBreakerRegistry()


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    reset_timeout: float = 30.0,
):
    """
    断路器装饰器
    
    用法:
        @circuit_breaker("binance_klines")
        async def get_klines(symbol):
            ...
    """
    def decorator(func):
        cb = _registry.get(name, failure_threshold, reset_timeout)
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await cb.call(func, *args, **kwargs)
        
        # 暴露断路器实例，便于检查状态
        wrapper.circuit_breaker = cb
        return wrapper
    
    return decorator


def get_circuit_breaker(name: str) -> Optional[CircuitBreakerInstance]:
    """获取已注册的断路器"""
    return _registry._breakers.get(name)


def get_all_circuit_breaker_stats() -> list[dict]:
    """获取所有断路器统计 (用于 /health 端点)"""
    return _registry.all_stats()
