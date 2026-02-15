"""
Trade Reflector - AI 反思记忆
==============================
借鉴 TradingAgents-CN 的 Reflector

每笔交易结束后:
1. 收集交易上下文 (入场指标、K线、当时AI的判断)
2. 对比实际盈亏结果
3. AI 总结经验教训
4. 写入记忆库 → 下次决策时参考
"""

import json
from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from datetime import datetime

from loguru import logger

from app.services.ai.providers import BaseProvider, ChatMessage


@dataclass
class TradeRecord:
    """交易记录 (用于反思)"""
    symbol: str
    side: str               # buy / sell
    entry_price: float
    exit_price: float
    pnl: float              # 盈亏金额
    pnl_pct: float           # 盈亏百分比
    hold_duration: str       # 持仓时长
    strategy_name: str
    entry_reason: str        # AI 当时的入场理由
    indicators_at_entry: Dict[str, Any]  # 入场时的指标快照
    indicators_at_exit: Dict[str, Any]   # 出场时的指标快照


@dataclass
class Reflection:
    """反思结果"""
    trade_symbol: str
    trade_result: str       # "win" / "loss"
    what_went_right: str    # 做对了什么
    what_went_wrong: str    # 做错了什么
    lesson: str             # 经验教训 (核心，会被存入记忆库)
    suggestion: str         # 改进建议
    raw_response: str = ""


class TradeReflector:
    """
    交易反思器 — 从每笔交易中学习
    
    这是系统 "进化" 的核心:
    - 赚了 → 分析为什么赚，下次类似情况还这么做
    - 亏了 → 分析为什么亏，下次类似情况如何避免
    """

    def __init__(self, provider: BaseProvider):
        self.provider = provider

    async def reflect(self, trade: TradeRecord) -> Reflection:
        """
        对一笔已完成的交易进行反思
        
        Args:
            trade: 交易记录
        
        Returns:
            Reflection 对象
        """
        try:
            messages = self._build_messages(trade)
            
            logger.info(
                f"[Reflector] 反思交易: {trade.symbol} "
                f"{'盈利' if trade.pnl >= 0 else '亏损'} {trade.pnl_pct:+.2f}%"
            )
            
            response = await self.provider.chat(
                messages=messages,
                temperature=0.4,
                max_tokens=1000,
            )
            
            reflection = self._parse_response(trade, response.content)
            reflection.raw_response = response.content
            
            logger.info(f"[Reflector] 经验总结: {reflection.lesson[:100]}...")
            
            return reflection
            
        except Exception as e:
            logger.error(f"[Reflector] 反思失败: {e}")
            result_type = "win" if trade.pnl >= 0 else "loss"
            return Reflection(
                trade_symbol=trade.symbol,
                trade_result=result_type,
                what_went_right="反思服务异常，无法分析",
                what_went_wrong="反思服务异常，无法分析",
                lesson=f"{trade.symbol} {trade.side} {trade.pnl_pct:+.2f}% (反思服务异常)",
                suggestion="",
            )

    def _build_messages(self, trade: TradeRecord) -> List[ChatMessage]:
        """构建反思 Prompt"""
        result_cn = "盈利" if trade.pnl >= 0 else "亏损"
        
        # 入场指标摘要
        entry_ind = trade.indicators_at_entry
        exit_ind = trade.indicators_at_exit
        
        system_prompt = """你是一位资深交易教练，负责分析已完成的交易并总结经验教训。

你的分析必须：
1. 客观评估交易决策的优劣
2. 从技术指标、K线形态、市场环境角度分析成败原因
3. 给出可操作的改进建议
4. 总结为一条简洁的经验教训（这条会存入记忆库，未来自动参考）

必须返回以下 JSON 格式:
```json
{
    "what_went_right": "做对了什么（50字内）",
    "what_went_wrong": "做错了什么（50字内）",
    "lesson": "核心经验教训（一句话，80字内，要具体可操作）",
    "suggestion": "改进建议（50字内）"
}
```"""

        user_msg = f"""请分析以下已完成的交易:

交易对: {trade.symbol}
方向: {trade.side}
策略: {trade.strategy_name}
入场价: {trade.entry_price}
出场价: {trade.exit_price}
结果: {result_cn} {trade.pnl_pct:+.2f}% (${trade.pnl:+.2f})
持仓时长: {trade.hold_duration}

入场时的判断理由: {trade.entry_reason}

入场时指标:
  RSI: {entry_ind.get('rsi', 'N/A')}
  MACD Histogram: {entry_ind.get('macd', {}).get('histogram', 'N/A') if isinstance(entry_ind.get('macd'), dict) else 'N/A'}
  量比: {entry_ind.get('volume_ratio', 'N/A')}

出场时指标:
  RSI: {exit_ind.get('rsi', 'N/A')}
  MACD Histogram: {exit_ind.get('macd', {}).get('histogram', 'N/A') if isinstance(exit_ind.get('macd'), dict) else 'N/A'}
  量比: {exit_ind.get('volume_ratio', 'N/A')}

请分析并返回 JSON。"""

        return [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_msg),
        ]

    def _parse_response(self, trade: TradeRecord, raw: str) -> Reflection:
        """解析反思结果"""
        import re
        
        result_type = "win" if trade.pnl >= 0 else "loss"
        
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return Reflection(
                    trade_symbol=trade.symbol,
                    trade_result=result_type,
                    what_went_right=data.get("what_went_right", ""),
                    what_went_wrong=data.get("what_went_wrong", ""),
                    lesson=data.get("lesson", ""),
                    suggestion=data.get("suggestion", ""),
                )
            except (json.JSONDecodeError, ValueError):
                pass
        
        # 兜底: 用原始文本
        return Reflection(
            trade_symbol=trade.symbol,
            trade_result=result_type,
            what_went_right="",
            what_went_wrong="",
            lesson=raw[:200] if raw else "反思解析失败",
            suggestion="",
        )

    @staticmethod
    def format_memories_for_prompt(memories: List[Dict]) -> str:
        """
        格式化历史记忆为文本 (供 AI 审核员使用)
        
        Args:
            memories: [{"symbol": ..., "lesson": ..., "trade_result": ..., "created_at": ...}]
        
        Returns:
            格式化的文本
        """
        if not memories:
            return "暂无历史交易经验。"
        
        parts = []
        for i, m in enumerate(memories[-5:], 1):  # 最多 5 条
            result_emoji = "✅" if m.get("trade_result") == "win" else "❌"
            parts.append(
                f"{i}. {result_emoji} [{m.get('symbol', '?')}] {m.get('lesson', 'N/A')}"
            )
        
        return "\n".join(parts)
