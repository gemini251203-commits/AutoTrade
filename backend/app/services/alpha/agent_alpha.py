"""
Agent Alpha — AI Agent → Insight 适配器
=========================================
将 agent/autopilot.py 的 AI 分析决策包装为 AlphaModel

关键变化:
- Agent 分析后只产出 Insight, 不再直接调用 create_order
- 交易执行由 Pipeline 的 Execution 层负责
- 保留 AI 的分析推理, 记录在 Insight.metadata 中
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


class AgentAlpha(AlphaModel):
    """
    AI Agent 适配器
    
    将 Agent 的自然语言决策转换为 Insight:
    - "开多/做多/open_long" → InsightDirection.UP
    - "开空/做空/open_short" → InsightDirection.DOWN
    - "观望/hold" → 不产出 Insight
    """
    
    def __init__(self, user_id: int, confidence_threshold: float = 0.5):
        super().__init__()
        self._user_id = user_id
        self._confidence_threshold = confidence_threshold
    
    def get_name(self) -> str:
        return "agent_ai"
    
    async def update(
        self,
        symbol: str,
        price: Decimal,
        ai_decision: Optional[str] = None,
        ai_confidence: float = 0.0,
        ai_reasoning: str = "",
        **kwargs,
    ) -> List[Insight]:
        """
        将 AI 决策转换为 Insight
        
        Args:
            symbol: 交易对
            price: 最新价格
            ai_decision: AI 的决策类型 ("open_long", "open_short", "hold" 等)
            ai_confidence: AI 自评的信心指数 (0.0 ~ 1.0)
            ai_reasoning: AI 的分析推理文本
        """
        if not ai_decision:
            return []
        
        # 解析方向
        decision_lower = ai_decision.lower()
        
        LONG_KEYWORDS = {"open_long", "做多", "开多", "买入开仓", "建仓做多"}
        SHORT_KEYWORDS = {"open_short", "做空", "开空", "卖出开仓", "建仓做空"}
        
        if decision_lower in LONG_KEYWORDS or any(k in decision_lower for k in LONG_KEYWORDS):
            direction = InsightDirection.UP
        elif decision_lower in SHORT_KEYWORDS or any(k in decision_lower for k in SHORT_KEYWORDS):
            direction = InsightDirection.DOWN
        else:
            # hold / 观望 → 不产出信号
            return []
        
        # 信心过滤
        if ai_confidence < self._confidence_threshold:
            logger.debug(
                f"[AgentAlpha] {symbol} confidence {ai_confidence:.2f} < "
                f"threshold {self._confidence_threshold:.2f}, skip"
            )
            return []
        
        # 信号强度
        if ai_confidence >= 0.8:
            strength = InsightStrength.STRONG
        elif ai_confidence >= 0.6:
            strength = InsightStrength.NORMAL
        else:
            strength = InsightStrength.WEAK
        
        insight = Insight(
            symbol=symbol,
            direction=direction,
            confidence=ai_confidence,
            source=self.get_name(),
            strength=strength,
            metadata={
                "decision": ai_decision,
                "reasoning": ai_reasoning[:500],  # 截断, 避免过长
                "user_id": self._user_id,
            },
        )
        
        return [insight]
