"""
断路器模式(Circuit Breaker)单元测试
======================================
测试 CircuitBreakerInstance 的状态机转换逻辑:
  CLOSED → (连续N次失败) → OPEN → (等待timeout) → HALF_OPEN → (成功) → CLOSED
  HALF_OPEN → (失败) → OPEN

纯单元测试, 不依赖数据库和网络请求。

运行方式:
    cd backend
    python -m pytest tests/test_circuit_breaker.py -v
"""

import sys
import os
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import time
import pytest

# 直接加载模块文件，绕过 app/core/__init__.py 的重依赖链 (passlib/jose)
_mod_path = os.path.join(os.path.dirname(__file__), "..", "app", "core", "circuit_breaker.py")
_spec = importlib.util.spec_from_file_location("circuit_breaker", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

CircuitBreakerInstance = _mod.CircuitBreakerInstance
CircuitBreakerError = _mod.CircuitBreakerError
CircuitState = _mod.CircuitState
CircuitBreakerRegistry = _mod.CircuitBreakerRegistry


# ============================================
# A. 初始状态测试
# ============================================

class TestCircuitBreakerInit:
    """断路器初始状态"""

    def test_initial_state_closed(self):
        """创建时应为 CLOSED 状态"""
        cb = CircuitBreakerInstance("test", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_initial_counters_zero(self):
        """初始计数器全部为 0"""
        cb = CircuitBreakerInstance("test")
        stats = cb.stats
        assert stats["failure_count"] == 0
        assert stats["total_calls"] == 0
        assert stats["total_successes"] == 0
        assert stats["total_failures"] == 0


# ============================================
# B. CLOSED → OPEN 转换测试
# ============================================

class TestClosedToOpen:
    """CLOSED → OPEN: 连续失败达到阈值"""

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        """连续失败达到阈值后应进入 OPEN"""
        cb = CircuitBreakerInstance("test", failure_threshold=3, reset_timeout=60)

        async def always_fail():
            raise RuntimeError("模拟失败")

        for i in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(always_fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_stays_closed_below_threshold(self):
        """失败次数未达阈值，保持 CLOSED"""
        cb = CircuitBreakerInstance("test", failure_threshold=5)

        async def always_fail():
            raise RuntimeError("模拟失败")

        for i in range(4):
            with pytest.raises(RuntimeError):
                await cb.call(always_fail)

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """中间的成功调用应重置连续失败计数"""
        cb = CircuitBreakerInstance("test", failure_threshold=3)

        async def fail():
            raise RuntimeError("fail")

        async def succeed():
            return "ok"

        # 失败 2 次
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        # 成功 1 次 → 重置计数
        result = await cb.call(succeed)
        assert result == "ok"

        # 再失败 2 次 → 还不到阈值(3)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        assert cb.state == CircuitState.CLOSED  # 仍然 CLOSED


# ============================================
# C. OPEN 状态: 拒绝调用
# ============================================

class TestOpenState:
    """OPEN 状态: 直接拒绝"""

    @pytest.mark.asyncio
    async def test_open_rejects_with_error(self):
        """OPEN 时调用应抛 CircuitBreakerError"""
        cb = CircuitBreakerInstance("test_svc", failure_threshold=2, reset_timeout=60)

        async def fail():
            raise RuntimeError("fail")

        # 触发 OPEN
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

        # OPEN 状态下调用
        with pytest.raises(CircuitBreakerError) as exc_info:
            await cb.call(fail)

        assert "test_svc" in str(exc_info.value)
        assert exc_info.value.retry_after > 0


# ============================================
# D. OPEN → HALF_OPEN 自动转换
# ============================================

class TestOpenToHalfOpen:
    """OPEN → HALF_OPEN: 超过 reset_timeout 后自动转换"""

    def test_transitions_after_timeout(self):
        """超时后查询状态应返回 HALF_OPEN"""
        cb = CircuitBreakerInstance("test", failure_threshold=2, reset_timeout=0.1)

        # 手动设置为 OPEN
        cb._state = CircuitState.OPEN
        cb._last_failure_time = time.monotonic() - 1  # 1 秒前失败

        # reset_timeout=0.1s, 已过 1s → 应该转为 HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN


# ============================================
# E. HALF_OPEN → CLOSED (恢复)
# ============================================

class TestHalfOpenRecovery:
    """HALF_OPEN → CLOSED: 探针成功"""

    @pytest.mark.asyncio
    async def test_recovers_on_success(self):
        """半开状态下探针成功 → 恢复为 CLOSED"""
        cb = CircuitBreakerInstance("test", failure_threshold=2, reset_timeout=0.01)

        async def fail():
            raise RuntimeError("fail")

        async def succeed():
            return "recovered"

        # 触发 OPEN
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        # 等待超时转为 HALF_OPEN
        await asyncio.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN

        # 探针成功
        result = await cb.call(succeed)
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED


# ============================================
# F. HALF_OPEN → OPEN (探针失败)
# ============================================

class TestHalfOpenFailure:
    """HALF_OPEN → OPEN: 探针失败"""

    @pytest.mark.asyncio
    async def test_reopens_on_probe_failure(self):
        """半开状态下探针失败 → 重新进入 OPEN"""
        cb = CircuitBreakerInstance("test", failure_threshold=2, reset_timeout=0.01)

        async def fail():
            raise RuntimeError("fail")

        # 触发 OPEN
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        # 等待转为 HALF_OPEN
        await asyncio.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN

        # 探针失败
        with pytest.raises(RuntimeError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN


# ============================================
# G. 统计数据准确性
# ============================================

class TestStatistics:
    """统计数据准确性"""

    @pytest.mark.asyncio
    async def test_counts_track_correctly(self):
        """总调用/成功/失败计数正确"""
        cb = CircuitBreakerInstance("test", failure_threshold=100)

        async def succeed():
            return "ok"

        async def fail():
            raise RuntimeError("fail")

        # 3 次成功
        for _ in range(3):
            await cb.call(succeed)

        # 2 次失败
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(fail)

        stats = cb.stats
        assert stats["total_calls"] == 5
        assert stats["total_successes"] == 3
        assert stats["total_failures"] == 2
        assert stats["success_rate"] == "60.0%"


# ============================================
# H. Registry 测试
# ============================================

class TestCircuitBreakerRegistry:
    """断路器注册表"""

    def test_creates_new_breaker(self):
        """首次获取时创建新断路器"""
        registry = CircuitBreakerRegistry()
        cb = registry.get("svc_a")
        assert cb.name == "svc_a"
        assert cb.state == CircuitState.CLOSED

    def test_returns_same_instance(self):
        """同名返回同一个实例"""
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("svc_a")
        cb2 = registry.get("svc_a")
        assert cb1 is cb2

    def test_different_names_different_instances(self):
        """不同名称返回不同实例"""
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("svc_a")
        cb2 = registry.get("svc_b")
        assert cb1 is not cb2

    def test_all_stats(self):
        """注册表应能汇总所有断路器的统计"""
        registry = CircuitBreakerRegistry()
        registry.get("svc_a")
        registry.get("svc_b")
        registry.get("svc_c")
        
        stats = registry.all_stats()
        assert len(stats) == 3
        names = {s["name"] for s in stats}
        assert names == {"svc_a", "svc_b", "svc_c"}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
