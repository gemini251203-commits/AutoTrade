"""
Event Bus
==========
轻量级异步事件总线 — LEAN 风格的组件解耦

设计原则:
- 同进程内事件传递 (不用 Redis Pub/Sub, 避免延迟)
- 支持优先级 (风控事件优先处理)
- 支持事件过滤 (按 symbol 过滤)
- 线程安全 (asyncio 原生)

用法:
    from app.core.event_bus import event_bus, Event, EventType

    # 发布事件
    await event_bus.emit(Event(
        type=EventType.TICK,
        data={"symbol": "ETHUSDT", "price": Decimal("3200")},
        source="price_stream"
    ))

    # 订阅事件
    @event_bus.on(EventType.TICK)
    async def handle_tick(event: Event):
        print(f"Price: {event.data['price']}")

    # 带过滤的订阅
    @event_bus.on(EventType.TICK, filter=lambda e: e.data["symbol"] == "BTCUSDT")
    async def handle_btc_only(event: Event):
        ...
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from loguru import logger


# ============================================================
# 事件类型
# ============================================================

class EventType(str, Enum):
    """事件类型枚举"""
    
    # --- 数据层 ---
    TICK          = "tick"           # 价格更新 {symbol, price, volume}
    KLINE         = "kline"         # K线更新 {symbol, interval, ohlcv}
    
    # --- Alpha 层 ---
    INSIGHT       = "insight"       # Alpha 信号 {Insight 对象}
    
    # --- Portfolio 层 ---
    TARGET        = "target"        # 仓位目标 {PortfolioTarget 对象}
    
    # --- Execution 层 ---
    ORDER_CREATED = "order_created" # 订单创建 {order_id, symbol, side, qty}
    ORDER_FILLED  = "order_filled"  # 订单成交 {order_id, price, qty}
    ORDER_CANCELLED = "order_cancelled"  # 订单取消
    
    # --- Risk 层 ---
    RISK_CHECK    = "risk_check"    # 风控检查请求
    RISK_ALERT    = "risk_alert"    # 风控警报 (预警, 不阻断)
    RISK_VETO     = "risk_veto"     # 风控否决 (一票否决, 阻断)
    LIQUIDATION   = "liquidation"   # 强平事件
    
    # --- 系统 ---
    SYSTEM_START  = "system_start"  # 系统启动
    SYSTEM_STOP   = "system_stop"   # 系统关闭


# ============================================================
# 事件数据
# ============================================================

@dataclass
class Event:
    """事件对象"""
    type: EventType
    data: Dict[str, Any]
    source: str = ""                          # 发布者标识
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # 元数据
    user_id: Optional[int] = None             # 关联用户
    correlation_id: Optional[str] = None      # 关联追踪 ID
    
    def __repr__(self) -> str:
        symbol = self.data.get("symbol", "")
        return f"<Event({self.type.value}, {symbol}, src={self.source})>"


# ============================================================
# 订阅者
# ============================================================

@dataclass
class Subscriber:
    """事件订阅者"""
    handler: Callable
    filter_fn: Optional[Callable[[Event], bool]] = None
    priority: int = 0      # 越大越优先 (风控=100, 普通=0)
    name: str = ""          # 调试用名称
    
    def __repr__(self) -> str:
        return f"<Subscriber({self.name or self.handler.__name__}, priority={self.priority})>"


# ============================================================
# 事件总线
# ============================================================

class EventBus:
    """
    异步事件总线
    
    特性:
    - 按优先级排序处理 (风控最先)
    - 支持事件过滤 (减少不必要处理)
    - RISK_VETO 会阻断后续处理
    - 错误隔离 (单个 handler 失败不影响其他)
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Subscriber]] = {}
        self._global_subscribers: List[Subscriber] = []  # 监听所有事件
        self._circuit_breaker: bool = False               # 熔断状态
        self._stats: Dict[str, int] = {}                  # 事件统计
    
    # --- 订阅 ---
    
    def subscribe(
        self,
        event_type: EventType,
        handler: Callable,
        priority: int = 0,
        filter_fn: Optional[Callable] = None,
        name: str = "",
    ) -> None:
        """订阅某类事件"""
        sub = Subscriber(
            handler=handler,
            filter_fn=filter_fn,
            priority=priority,
            name=name or handler.__name__,
        )
        
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        self._subscribers[event_type].append(sub)
        # 按优先级排序 (高优先级在前)
        self._subscribers[event_type].sort(key=lambda s: -s.priority)
        
        logger.debug(
            f"[EventBus] Subscribed: {sub.name} → {event_type.value} "
            f"(priority={priority})"
        )
    
    def on(
        self,
        event_type: EventType,
        priority: int = 0,
        filter_fn: Optional[Callable] = None,
    ):
        """装饰器方式订阅"""
        def decorator(func):
            self.subscribe(event_type, func, priority, filter_fn, name=func.__name__)
            return func
        return decorator
    
    def unsubscribe(self, event_type: EventType, handler: Callable) -> None:
        """取消订阅"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                s for s in self._subscribers[event_type]
                if s.handler != handler
            ]
    
    # --- 发布 ---
    
    async def emit(self, event: Event) -> bool:
        """
        发布事件
        
        Returns:
            True: 正常处理
            False: 被风控否决或熔断
        """
        # 熔断检查 (只允许 RISK 类事件通过)
        if self._circuit_breaker and event.type not in (
            EventType.RISK_VETO, EventType.RISK_ALERT,
            EventType.SYSTEM_STOP, EventType.LIQUIDATION,
        ):
            logger.warning(f"[EventBus] CIRCUIT BREAKER — blocked: {event}")
            return False
        
        # 统计
        key = event.type.value
        self._stats[key] = self._stats.get(key, 0) + 1
        
        # 获取订阅者 (已按优先级排序)
        subscribers = self._subscribers.get(event.type, [])
        
        if not subscribers:
            return True
        
        # 逐个调用 (顺序执行, 支持风控拦截)
        for sub in subscribers:
            # 过滤检查
            if sub.filter_fn:
                try:
                    if not sub.filter_fn(event):
                        continue
                except Exception:
                    continue
            
            try:
                result = sub.handler(event)
                if asyncio.iscoroutine(result):
                    result = await result
                
                # 如果风控返回 VETO, 阻断后续
                if result is False and event.type in (
                    EventType.RISK_CHECK, EventType.TARGET
                ):
                    logger.warning(
                        f"[EventBus] VETOED by {sub.name}: {event}"
                    )
                    return False
                    
            except Exception as e:
                logger.error(
                    f"[EventBus] Handler error: {sub.name} → {e}"
                )
                # 错误隔离 — 继续处理其他 handler
                continue
        
        return True
    
    async def emit_fire_and_forget(self, event: Event) -> None:
        """发布事件但不等待处理完成 (用于非关键事件)"""
        asyncio.create_task(self.emit(event))
    
    # --- 熔断 ---
    
    def activate_circuit_breaker(self, reason: str = "") -> None:
        """激活熔断器 — 阻断所有非风控事件"""
        self._circuit_breaker = True
        logger.critical(f"[EventBus] 🔥 CIRCUIT BREAKER ACTIVATED: {reason}")
    
    def deactivate_circuit_breaker(self) -> None:
        """解除熔断"""
        self._circuit_breaker = False
        logger.info("[EventBus] Circuit breaker deactivated")
    
    @property
    def is_circuit_breaker_active(self) -> bool:
        return self._circuit_breaker
    
    # --- 调试 ---
    
    def get_stats(self) -> Dict[str, int]:
        """获取事件统计"""
        return dict(self._stats)
    
    def get_subscriber_count(self, event_type: EventType) -> int:
        return len(self._subscribers.get(event_type, []))
    
    def reset(self) -> None:
        """重置 (测试用)"""
        self._subscribers.clear()
        self._global_subscribers.clear()
        self._circuit_breaker = False
        self._stats.clear()


# ============================================================
# 全局单例
# ============================================================

event_bus = EventBus()
