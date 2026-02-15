"""
AI Reviewer - AI 审核员
========================
策略说"可以考虑" → AI 决定"要不要做"

借鉴 TradingAgents-CN 的多空博弈:
- 从看多角度分析候选信号
- 从看空角度找反对理由  
- 综合判断 + 历史经验 → 最终决策

输入: 候选信号 + 指标快照 + K线 + 用户 ai_prompt + 历史记忆
输出: ReviewResult(approve, confidence, reason)
"""

import json
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Any

from loguru import logger

from app.services.ai.providers import BaseProvider, ChatMessage, ChatResponse
from .indicators import calculate_all_indicators
from .strategy import Signal


@dataclass
class ReviewResult:
    """AI 审核结果"""
    approve: bool           # 是否批准执行
    confidence: float       # 置信度 0-1
    reason: str             # AI 给出的理由
    bull_analysis: str = "" # 看多分析
    bear_analysis: str = "" # 看空分析
    raw_response: str = ""  # AI 原始响应


class AIReviewer:
    """
    AI 审核员 — 策略定方向，AI 做判断
    
    流程:
    1. 收集市场上下文 (指标快照 + 最近K线)
    2. 注入用户的 ai_prompt (交易风格)
    3. 注入历史经验 (反思记忆)
    4. 让 AI 从多空两面分析
    5. 返回结构化审核结果
    """

    def __init__(self, provider: BaseProvider):
        self.provider = provider

    async def review(
        self,
        signal: Signal,
        klines: List[Dict],
        memories: Optional[List[Dict]] = None,
    ) -> ReviewResult:
        """
        审核候选信号
        
        Args:
            signal: 策略引擎产生的候选信号
            klines: K 线数据
            memories: 历史交易经验 [{"situation": ..., "lesson": ...}]
        
        Returns:
            ReviewResult
        """
        try:
            # 1. 构建上下文
            indicators = calculate_all_indicators(klines)
            context = self._build_context(signal, klines, indicators, memories)
            
            # 2. 构建 Prompt
            messages = self._build_messages(signal, context)
            
            # 3. 调用 AI
            logger.info(
                f"[AIReviewer] 审核信号: {signal.symbol} "
                f"{signal.signal_type.value} {signal.side.value if signal.side else '?'}"
            )
            
            response = await self.provider.chat(
                messages=messages,
                temperature=0.3,  # 低温度 = 更确定性
                max_tokens=1500,
            )
            
            # 4. 解析结果
            result = self._parse_response(response.content)
            result.raw_response = response.content
            
            logger.info(
                f"[AIReviewer] 结果: {'✅ 批准' if result.approve else '❌ 拒绝'} "
                f"(confidence={result.confidence:.0%})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[AIReviewer] 审核失败: {e}")
            # 审核失败 = 保守起见拒绝
            return ReviewResult(
                approve=False,
                confidence=0.0,
                reason=f"AI 审核服务异常: {str(e)}，保守起见拒绝执行",
            )

    def _build_context(
        self,
        signal: Signal,
        klines: List[Dict],
        indicators: Dict,
        memories: Optional[List[Dict]],
    ) -> str:
        """构建市场上下文文本"""
        parts = []
        
        # 当前价格和指标
        price_info = indicators.get("price", {})
        parts.append(
            f"【当前价格】\n"
            f"  Close: {price_info.get('close', 'N/A')}\n"
            f"  Open: {price_info.get('open', 'N/A')}\n"
            f"  High: {price_info.get('high', 'N/A')}\n"
            f"  Low: {price_info.get('low', 'N/A')}"
        )
        
        # 技术指标
        rsi = indicators.get("rsi")
        macd = indicators.get("macd", {})
        ema = indicators.get("ema", {})
        bollinger = indicators.get("bollinger", {})
        kdj = indicators.get("kdj", {})
        atr = indicators.get("atr")
        vol_ratio = indicators.get("volume_ratio")
        
        parts.append(
            f"【技术指标】\n"
            f"  RSI(14): {rsi}\n"
            f"  MACD: {macd.get('macd') if macd else 'N/A'}, "
            f"Signal: {macd.get('signal') if macd else 'N/A'}, "
            f"Histogram: {macd.get('histogram') if macd else 'N/A'}\n"
            f"  EMA20: {ema.get('ema_20', 'N/A')}, EMA50: {ema.get('ema_50', 'N/A')}\n"
            f"  Bollinger: Upper={bollinger.get('upper') if bollinger else 'N/A'}, "
            f"Lower={bollinger.get('lower') if bollinger else 'N/A'}\n"
            f"  KDJ: K={kdj.get('k') if kdj else 'N/A'}, "
            f"D={kdj.get('d') if kdj else 'N/A'}, "
            f"J={kdj.get('j') if kdj else 'N/A'}\n"
            f"  ATR: {atr}\n"
            f"  量比: {vol_ratio}"
        )
        
        # 支撑阻力
        sr = indicators.get("support_resistance", {})
        if sr:
            s_levels = sr.get("support", [])[:3]
            r_levels = sr.get("resistance", [])[:3]
            sr_text = "【支撑/阻力位】\n"
            for s in s_levels:
                sr_text += f"  支撑: {s['level']:.2f} (强度={s['strength']}, 距离={s['distance_pct']}%)\n"
            for r in r_levels:
                sr_text += f"  阻力: {r['level']:.2f} (强度={r['strength']}, 距离={r['distance_pct']}%)\n"
            parts.append(sr_text.strip())
        
        # K 线形态
        patterns = indicators.get("patterns", {})
        active_patterns = [k for k, v in patterns.items() if v]
        if active_patterns:
            parts.append(f"【检测到的K线形态】\n  {', '.join(active_patterns)}")
        else:
            parts.append("【检测到的K线形态】\n  无明显形态")
        
        # 最近 K 线
        recent = klines[-5:] if len(klines) >= 5 else klines
        kline_text = "【最近K线】\n"
        for k in recent:
            change = ((k["close"] - k["open"]) / k["open"] * 100) if k["open"] > 0 else 0
            candle = "阳" if k["close"] > k["open"] else "阴"
            kline_text += (
                f"  {candle}线 O={k['open']:.2f} H={k['high']:.2f} "
                f"L={k['low']:.2f} C={k['close']:.2f} "
                f"({change:+.2f}%) Vol={k['volume']:.0f}\n"
            )
        parts.append(kline_text.strip())
        
        # 策略条件评估结果
        cond_text = "【策略条件评估】\n"
        for c in signal.conditions_met:
            cond_text += f"  ✅ {c}\n"
        for c in signal.conditions_failed:
            cond_text += f"  ❌ {c}\n"
        parts.append(cond_text.strip())
        
        # 历史经验
        if memories:
            mem_text = "【历史交易经验】\n"
            for m in memories[-3:]:  # 最多 3 条
                mem_text += f"  - {m.get('lesson', 'N/A')}\n"
            parts.append(mem_text.strip())
        else:
            parts.append("【历史交易经验】\n  暂无历史经验")
        
        return "\n\n".join(parts)

    def _build_messages(self, signal: Signal, context: str) -> List[ChatMessage]:
        """构建 AI 对话消息"""
        # 用户自定义的 ai_prompt (如果有)
        user_style = signal.ai_prompt.strip() if signal.ai_prompt else ""
        
        system_prompt = f"""你是一位专业的加密货币交易审核员。你的职责是审核策略引擎产生的候选交易信号。

核心原则:
1. 策略已经触发了候选信号，你需要从**多空两个角度**综合判断是否应该执行
2. 你必须考虑当前市场环境、技术指标、K线形态和历史经验
3. 宁可错过机会，也不要冒不必要的风险（保守为主）
4. 必须返回结构化 JSON 结果

{('用户交易风格指示: ' + user_style) if user_style else ''}

你必须严格按以下 JSON 格式返回（不要添加任何其他内容）:
```json
{{
    "approve": true或false,
    "confidence": 0.0到1.0,
    "bull_analysis": "看多理由（50字内）",
    "bear_analysis": "看空理由（50字内）",
    "reason": "最终判断理由（100字内）"
}}
```"""

        user_msg = (
            f"交易对: {signal.symbol}\n"
            f"信号类型: {signal.signal_type.value}\n"
            f"方向: {signal.side.value if signal.side else 'unknown'}\n"
            f"策略: {signal.strategy_name}\n\n"
            f"{context}\n\n"
            f"请审核以上信号，返回 JSON 结果。"
        )

        return [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_msg),
        ]

    def _parse_response(self, raw: str) -> ReviewResult:
        """解析 AI 响应为 ReviewResult"""
        # 尝试从响应中提取 JSON
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        
        if json_match:
            try:
                data = json.loads(json_match.group())
                return ReviewResult(
                    approve=bool(data.get("approve", False)),
                    confidence=float(data.get("confidence", 0.5)),
                    reason=str(data.get("reason", "")),
                    bull_analysis=str(data.get("bull_analysis", "")),
                    bear_analysis=str(data.get("bear_analysis", "")),
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[AIReviewer] JSON 解析失败: {e}")
        
        # JSON 解析失败 → 尝试从文本中提取关键信息
        approve = any(
            kw in raw.lower()
            for kw in ["approve", "确认", "批准", "买入", "执行", '"approve": true']
        )
        
        return ReviewResult(
            approve=approve,
            confidence=0.5,
            reason=raw[:200] if raw else "AI 响应解析失败",
        )
