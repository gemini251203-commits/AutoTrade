"""
Alpha Model Base — 策略基类抽象
================================
LEAN 风格: Alpha Model 只负责产出 Insight (信号), 绝不直接下单

设计原则:
- 所有策略 (YAML/AI Agent/网格) 统一实现 AlphaModel 接口
- 输出标准化的 Insight 对象
- 与 EventBus 自动集成 (订阅 TICK, 发布 INSIGHT)

类比:
    LEAN:      IAlphaModel.Update() → List[Insight]
    AutoTrade: AlphaModel.update()  → List[Insight]
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger
from app.core.time_utils import utc_now


# ============================================================
# Insight — Alpha 模型的唯一输出
# ============================================================

class InsightDirection(str, Enum):
    """信号方向"""
    UP   = "up"       # 看涨
    DOWN = "down"     # 看跌
    FLAT = "flat"     # 震荡/无方向


class InsightStrength(str, Enum):
    """信号强度 (辅助 confidence)"""
    STRONG  = "strong"     # 强烈信号 (多个指标共振)
    NORMAL  = "normal"     # 普通信号
    WEAK    = "weak"       # 弱信号 (仅供参考)


@dataclass
class Insight:
    """
    Alpha 信号 — 策略的唯一输出物
    
    对标 LEAN 的 Insight 类:
    - symbol: 交易对
    - direction: 看涨/看跌/震荡
    - confidence: 0.0 ~ 1.0 (决定仓位大小)
    - period: 预测有效期
    - source: 产生信号的 Alpha 名称
    
    注意: Insight 绝不包含仓位大小、杠杆等参数！
    那些由 Portfolio Model 决定。
    """
    symbol: str                                     # "ETHUSDT"
    direction: InsightDirection                     # UP / DOWN / FLAT
    confidence: float                               # 0.0 ~ 1.0
    source: str                                     # "yaml:rsi_oversold" / "agent_ai" / "grid"
    
    # 可选
    period: timedelta = field(default_factory=lambda: timedelta(hours=1))
    strength: InsightStrength = InsightStrength.NORMAL
    magnitude: float = 0.0                          # 预期波幅 %
    
    # 元数据 (策略自定义)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 自动填充
    generated_at: datetime = field(default_factory=lambda: utc_now())
    
    # 风控参数建议 (可选, Portfolio 可以覆盖)
    suggested_stop_loss_pct: Optional[float] = None     # 建议止损 % (e.g. 2.0)
    suggested_take_profit_pct: Optional[float] = None   # 建议止盈 %
    suggested_leverage: Optional[int] = None             # 建议杠杆
    
    @property
    def is_actionable(self) -> bool:
        """是否可执行 (排除 FLAT 和低信心)"""
        return (
            self.direction != InsightDirection.FLAT
            and self.confidence >= 0.3
        )
    
    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return utc_now() > self.generated_at + self.period
    
    def summary(self) -> str:
        """可读摘要"""
        arrow = "📈" if self.direction == InsightDirection.UP else "📉" if self.direction == InsightDirection.DOWN else "➡️"
        return (
            f"{arrow} {self.symbol} {self.direction.value.upper()} "
            f"(confidence={self.confidence:.0%}, src={self.source})"
        )
    
    def __repr__(self) -> str:
        return self.summary()


# ============================================================
# AlphaModel — 策略基类
# ============================================================

class AlphaModel(ABC):
    """
    Alpha 模型基类 — 所有策略的"参谋部"
    
    子类只需实现:
    - update(): 接收市场数据, 产出 Insight 列表
    - get_name(): 返回策略名称
    
    框架自动处理:
    - EventBus 订阅/发布
    - 信号去重
    - 日志记录
    """
    
    def __init__(self):
        self._last_insights: Dict[str, Insight] = {}   # symbol → 最新 Insight
        self._total_signals: int = 0
        self._enabled: bool = True
    
    @abstractmethod
    async def update(self, symbol: str, price: Decimal, **kwargs) -> List[Insight]:
        """
        核心方法 — 接收数据, 产出信号
        
        Args:
            symbol: 交易对
            price: 最新价格
            **kwargs: 扩展数据 (klines, indicators, etc.)
        
        Returns:
            Insight 列表 (可为空 = 无信号)
        
        重要: 绝不直接下单！只产出 Insight。
        """
        ...
    
    @abstractmethod
    def get_name(self) -> str:
        """返回策略名称 (用于日志/追踪)"""
        ...
    
    # --- 辅助方法 ---
    
    def enable(self) -> None:
        """启用"""
        self._enabled = True
        logger.info(f"[Alpha:{self.get_name()}] Enabled")
    
    def disable(self) -> None:
        """禁用"""
        self._enabled = False
        logger.info(f"[Alpha:{self.get_name()}] Disabled")
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    
    def get_last_insight(self, symbol: str) -> Optional[Insight]:
        """获取某品种的最新 Insight"""
        return self._last_insights.get(symbol)
    
    def get_stats(self) -> dict:
        """统计信息"""
        return {
            "name": self.get_name(),
            "enabled": self._enabled,
            "total_signals": self._total_signals,
            "active_insights": len(self._last_insights),
        }
    
    async def safe_update(self, symbol: str, price: Decimal, **kwargs) -> List[Insight]:
        """
        安全包装 — 捕获异常, 记录日志, 更新内部状态
        (由 Pipeline 调用, 不要直接调用 update)
        """
        if not self._enabled:
            return []
        
        try:
            insights = await self.update(symbol, price, **kwargs)
            
            # 记录
            for insight in insights:
                self._last_insights[insight.symbol] = insight
                self._total_signals += 1
                logger.info(
                    f"[Alpha:{self.get_name()}] {insight.summary()}"
                )
            
            return insights
            
        except Exception as e:
            logger.error(
                f"[Alpha:{self.get_name()}] Error processing "
                f"{symbol} @ {price}: {e}"
            )
            return []
