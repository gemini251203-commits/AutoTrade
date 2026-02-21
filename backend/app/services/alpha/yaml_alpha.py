"""
YAML Alpha — YAML 策略 → Insight 适配器
=========================================
将现有 quant/strategy.py 的 StrategyEngine 包装为 AlphaModel

功能:
- 复用现有 YAML 解析 + 条件评估引擎
- 将 Signal 输出转换为标准 Insight
- 支持多时间框架 K 线
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.alpha.base import (
    AlphaModel,
    Insight,
    InsightDirection,
    InsightStrength,
)


class YamlAlpha(AlphaModel):
    """
    YAML 策略适配器
    
    将 quant/strategy.py 的 StrategyEngine 包装为 AlphaModel:
    - parse_yaml() → 解析策略配置
    - evaluate()   → 评估条件 → Signal
    - Signal       → Insight (标准化转换)
    """
    
    def __init__(self, yaml_config: str, strategy_name: str = ""):
        super().__init__()
        
        from app.services.quant.strategy import StrategyEngine
        
        self._engine = StrategyEngine()
        self._config = self._engine.parse_yaml(yaml_config)
        self._strategy_name = strategy_name or self._config.get("name", "yaml_strategy")
    
    def get_name(self) -> str:
        return f"yaml:{self._strategy_name}"
    
    async def update(
        self,
        symbol: str,
        price: Decimal,
        klines_map: Optional[Dict[str, list]] = None,
        **kwargs,
    ) -> List[Insight]:
        """
        评估 YAML 策略，产出 Insight
        
        Args:
            symbol: 交易对
            price: 最新价格
            klines_map: 多时间框架 K 线 {"1h": [...], "4h": [...]}
        """
        if not klines_map:
            return []
        
        # 覆盖策略配置中的 symbol
        config = dict(self._config)
        config["symbol"] = symbol
        
        # 调用现有引擎评估
        signal = self._engine.evaluate(config, klines_map=klines_map)
        
        if not signal.has_signal:
            return []
        
        # Signal → Insight 转换
        if signal.side and signal.side.value == "buy":
            direction = InsightDirection.UP
        elif signal.side and signal.side.value == "sell":
            direction = InsightDirection.DOWN
        else:
            direction = InsightDirection.FLAT
        
        # 信号强度判定
        if signal.confidence >= 0.8:
            strength = InsightStrength.STRONG
        elif signal.confidence >= 0.5:
            strength = InsightStrength.NORMAL
        else:
            strength = InsightStrength.WEAK
        
        # 从 risk_config 提取建议参数
        risk_config = signal.risk_config or {}
        
        insight = Insight(
            symbol=symbol,
            direction=direction,
            confidence=signal.confidence,
            source=self.get_name(),
            strength=strength,
            metadata={
                "signal_type": signal.signal_type.value,
                "conditions_met": [str(c) for c in signal.conditions_met],
                "conditions_failed": [str(c) for c in signal.conditions_failed],
                "summary": signal.summary(),
            },
            suggested_stop_loss_pct=risk_config.get("stop_loss_pct"),
            suggested_take_profit_pct=risk_config.get("take_profit_pct"),
            suggested_leverage=risk_config.get("leverage"),
        )
        
        return [insight]
