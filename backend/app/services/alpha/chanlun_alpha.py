"""
Chanlun AI Alpha — 缠论 AI 研判信号模型
==========================================
继承 AlphaModel，结合 chanlun_utils 的几何计算 + AI 大模型的逻辑推理

核心原则:
  Python(chanlun_utils) 负责几何计算 → 结构化数据 → AI 负责缠论逻辑推理

流程:
  1. 获取 K 线
  2. chanlun_utils.analyze_chanlun() → 分型/笔/背驰 JSON
  3. 拼接 System Prompt + 数据 → 调用 AI
  4. 解析 AI 输出 → Insight
"""

import json
from decimal import Decimal
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.alpha.base import (
    AlphaModel,
    Insight,
    InsightDirection,
    InsightStrength,
)
from app.services.quant.chanlun_utils import analyze_chanlun


# ============================================================
# System Prompt
# ============================================================

CHANLUN_SYSTEM_PROMPT = """## 角色
你是一名严谨的**缠论分析专家**。你只基于结构化的顶底分型数据和 MACD 动能数据进行逻辑推理，**绝不凭空想象K线走势**。

## 你会收到的数据
1. **趋势** (trend): up / down / consolidation / unknown
2. **分型序列** (fractals): Python 已为你计算好的经过包含处理后的顶分型和底分型，含价格和时间。
3. **笔序列** (strokes): 由分型连接而成的笔，含方向(up/down)和起止价格。
4. **当前进行中的笔** (current_stroke): 尚未完成的最新一笔。
5. **MACD 背驰检测** (macd_divergence):
   - has_top_divergence: 是否出现顶背驰（价格新高但动能衰竭）
   - has_bottom_divergence: 是否出现底背驰（价格新低但动能衰竭）
   - area_ratio: 当前笔动能/前一笔动能 (<1 = 衰竭)
6. **你的上一次分析记忆** (scratchpad)

## 分析框架
请严格按照以下步骤推理：

### 第一步：识别当前级别走势类型
- 上升趋势：连续出现更高的底分型 + 更高的顶分型
- 下降趋势：连续出现更低的顶分型 + 更低的底分型
- 盘整：顶底分型交替出现但无法突破前高/前低

### 第二步：判断买卖点
- **一买（第一类买点）**: 下降趋势中，最新下降笔出现**底背驰** (has_bottom_divergence=true 且 area_ratio < 0.8)。→ open_long
- **一卖（第一类卖点）**: 上升趋势中，最新上升笔出现**顶背驰** (has_top_divergence=true 且 area_ratio < 0.8)。→ open_short
- **二买（第二类买点）**: 一买之后回调不破前低（最新底分型价格 > 前一底分型价格）。→ open_long
- **二卖（第二类卖点）**: 一卖之后反弹不破前高（最新顶分型价格 < 前一顶分型价格）。→ open_short
- **三买（第三类买点）**: 中枢上沿上方回踩不进中枢，底分型高于中枢高点。→ open_long
- **三卖（第三类卖点）**: 中枢下沿下方反弹不进中枢，顶分型低于中枢低点。→ open_short

### 第三步：信心评分 (confidence: 0.0 ~ 1.0)
- 背驰明显度 (area_ratio 越小越确定): +0.2 ~ +0.3
- 趋势方向明确: +0.1 ~ +0.2
- 当前笔走出足够幅度 (>2%): +0.1
- 分型数量充足 (≥6): +0.1

## 输出格式
严格输出以下 JSON，无其他内容:
```json
{
  "decision": "open_long" | "open_short" | "hold",
  "signal_type": "1b" | "1s" | "2b" | "2s" | "3b" | "3s" | null,
  "confidence": 0.0,
  "reasoning": "简要3行推理",
  "scratchpad": "更新你的记忆，记录当前走势阶段、已识别的买卖点、等待什么条件"
}
```

## 禁令
- ❌ 你不可以描述"K线形态像xxx"——你没有看图的能力。
- ❌ 你不可以编造不存在的分型或笔——所有几何数据均由 Python 提供。
- ❌ 你不可以给出模棱两可的答案——要么有信号要么 hold。
- ❌ confidence < 0.5 时**必须** decision = "hold"。"""


# ============================================================
# ChanlunAIAlpha
# ============================================================

class ChanlunAIAlpha(AlphaModel):
    """
    缠论 AI 研判 Alpha 模型
    
    Python 几何计算 → AI 逻辑推理 → Insight
    """
    
    def __init__(
        self,
        user_id: int,
        confidence_threshold: float = 0.5,
        divergence_threshold: float = 0.8,
        kline_count: int = 100,
    ):
        super().__init__()
        self._user_id = user_id
        self._confidence_threshold = confidence_threshold
        self._divergence_threshold = divergence_threshold
        self._kline_count = kline_count
        self._scratchpad: str = ""  # AI 的缠论记忆
    
    def get_name(self) -> str:
        return "chanlun_ai"
    
    async def update(
        self,
        symbol: str,
        price: Decimal,
        klines_map: Optional[Dict[str, list]] = None,
        **kwargs,
    ) -> List[Insight]:
        """
        缠论 AI 研判
        
        Args:
            symbol: 交易对
            price: 最新价格
            klines_map: K线数据 {"1h": [...], "4h": [...]}
        """
        if not klines_map:
            return []
        
        # 取第一个可用的时间框架
        interval = None
        klines = None
        for k, v in klines_map.items():
            if v and len(v) >= 30:
                interval = k
                klines = v[-self._kline_count:]  # 截取最近 N 根
                break
        
        if not klines:
            return []
        
        # ===== 1. Python 几何计算 =====
        chanlun_data = analyze_chanlun(klines)
        
        if chanlun_data.get("error"):
            logger.warning(f"[ChanlunAI] {symbol} 分析失败: {chanlun_data['error']}")
            return []
        
        # ===== 2. 构建 AI Prompt =====
        user_message = self._build_user_message(symbol, interval, chanlun_data)
        
        # ===== 3. 调用 AI =====
        try:
            ai_response = await self._call_ai(user_message)
        except Exception as e:
            logger.error(f"[ChanlunAI] AI 调用失败: {e}")
            return []
        
        if not ai_response:
            return []
        
        # ===== 4. 解析 AI 输出 → Insight =====
        return self._parse_response(symbol, price, ai_response, chanlun_data)
    
    def _build_user_message(
        self,
        symbol: str,
        interval: str,
        chanlun_data: dict,
    ) -> str:
        """构建发给 AI 的用户消息"""
        parts = [
            f"## 缠论分析请求",
            f"交易对: {symbol}",
            f"K线周期: {interval}",
            f"",
            f"## Python 计算结果",
            f"```json",
            json.dumps(chanlun_data, ensure_ascii=False, indent=2),
            f"```",
        ]
        
        if self._scratchpad:
            parts.extend([
                f"",
                f"## 你的上一次分析记忆 (Scratchpad)",
                self._scratchpad,
            ])
        
        return "\n".join(parts)
    
    async def _call_ai(self, user_message: str) -> Optional[dict]:
        """调用 AI 大模型进行缠论分析"""
        from app.services.agent.brain import AIBrain
        
        brain = AIBrain(user_id=self._user_id)
        
        messages = [
            {"role": "system", "content": CHANLUN_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        
        try:
            response = await brain.chat(messages=messages, temperature=0.3)
        except Exception as e:
            logger.error(f"[ChanlunAI] brain.chat error: {e}")
            return None
        
        if not response:
            return None
        
        # 从回复中提取 JSON
        text = response if isinstance(response, str) else str(response)
        
        # 尝试提取 JSON
        try:
            # 先尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 尝试从 ```json ... ``` 中提取
        import re
        json_match = re.search(r'```json\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试从 { ... } 中提取
        brace_match = re.search(r'\{[^{}]*"decision"[^{}]*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"[ChanlunAI] 无法解析 AI 回复: {text[:200]}")
        return None
    
    def _parse_response(
        self,
        symbol: str,
        price: Decimal,
        ai_response: dict,
        chanlun_data: dict,
    ) -> List[Insight]:
        """解析 AI 回复 → Insight"""
        decision = ai_response.get("decision", "hold")
        confidence = float(ai_response.get("confidence", 0))
        signal_type = ai_response.get("signal_type")
        reasoning = ai_response.get("reasoning", "")
        scratchpad = ai_response.get("scratchpad", "")
        
        # 更新 scratchpad 记忆
        if scratchpad:
            self._scratchpad = scratchpad
        
        logger.info(
            f"[ChanlunAI] {symbol} decision={decision} "
            f"signal={signal_type} confidence={confidence:.2f} "
            f"reason={reasoning[:100]}"
        )
        
        # 信心过滤
        if confidence < self._confidence_threshold:
            return []
        
        # 方向映射
        if decision == "open_long":
            direction = InsightDirection.UP
        elif decision == "open_short":
            direction = InsightDirection.DOWN
        else:
            return []  # hold
        
        # 信号强度
        if confidence >= 0.8:
            strength = InsightStrength.STRONG
        elif confidence >= 0.6:
            strength = InsightStrength.NORMAL
        else:
            strength = InsightStrength.WEAK
        
        # 信号类型中文映射
        signal_names = {
            "1b": "缠论一买", "1s": "缠论一卖",
            "2b": "缠论二买", "2s": "缠论二卖",
            "3b": "缠论三买", "3s": "缠论三卖",
        }
        
        insight = Insight(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            source=self.get_name(),
            strength=strength,
            metadata={
                "signal_type": signal_type,
                "signal_name": signal_names.get(signal_type, "未知"),
                "reasoning": reasoning[:500],
                "trend": chanlun_data.get("trend", "unknown"),
                "divergence": chanlun_data.get("macd_divergence", {}),
                "user_id": self._user_id,
            },
        )
        
        return [insight]
