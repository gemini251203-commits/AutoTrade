"""
Multi-Agent Analysis Framework
===============================
多智能体分析框架

角色:
1. TechnicalAnalyst  - 技术分析师：K线形态、技术指标
2. SentimentAnalyst  - 市场情绪分析师：行情趋势、成交量
3. RiskAnalyst       - 风控分析师：仓位风险、资金安全
4. DecisionMaker     - 决策者：汇总各方观点，输出最终建议
5. MultiAgentOrchestrator - 编排器：协调多智能体工作流
"""

import json
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from loguru import logger

from app.models.market import Kline
from app.db.session import AsyncSessionLocal
from app.core.config import settings
from .providers import BaseProvider, ChatMessage, ChatResponse


# ==================== Data Models ====================

@dataclass
class AgentReport:
    """智能体分析报告"""
    agent_name: str              # 智能体名称
    role: str                    # 角色标识
    analysis: str                # 分析内容
    confidence: float = 0.0      # 信心度 (0-1)
    recommendation: str = ""     # 建议: bullish / bearish / neutral
    key_points: List[str] = field(default_factory=list)  # 关键观点
    warnings: List[str] = field(default_factory=list)     # 风险提示


@dataclass
class MultiAgentResult:
    """多智能体分析汇总结果"""
    symbol: str
    reports: List[AgentReport]           # 各智能体报告
    final_decision: str = ""             # 最终决策
    final_recommendation: str = "neutral"  # bullish / bearish / neutral
    confidence: float = 0.0
    reasoning: str = ""                  # 综合推理
    warnings: List[str] = field(default_factory=list)
    debate_rounds: int = 0


# ==================== Base Agent ====================

class BaseAgent(ABC):
    """智能体基类"""
    
    def __init__(self, name: str, role: str, provider: BaseProvider):
        self.name = name
        self.role = role
        self.provider = provider
    
    @abstractmethod
    async def analyze(self, symbol: str, context: Dict[str, Any]) -> AgentReport:
        """执行分析，返回报告"""
        pass
    
    async def _ask_ai(self, system_prompt: str, user_prompt: str) -> str:
        """调用 AI 生成分析"""
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_prompt),
        ]
        try:
            response = await self.provider.chat(messages, temperature=0.3, max_tokens=1500)
            return response.content
        except Exception as e:
            logger.error(f"[{self.name}] AI调用失败: {e}")
            return f"分析失败: {str(e)}"


# ==================== Technical Analyst ====================

class TechnicalAnalyst(BaseAgent):
    """
    📈 技术分析师
    
    分析K线数据和技术指标（RSI、MACD、EMA等）
    """
    
    def __init__(self, provider: BaseProvider):
        super().__init__("技术分析师", "technical", provider)
    
    async def analyze(self, symbol: str, context: Dict[str, Any]) -> AgentReport:
        """基于K线数据进行技术分析"""
        # 获取K线数据
        kline_summary = await self._get_kline_summary(symbol)
        indicators = context.get("indicators", {})
        
        system_prompt = """你是一位专业的加密货币技术分析师。
你需要基于提供的K线数据和技术指标，给出客观的技术分析。

你的分析必须包含:
1. 当前趋势判断（上涨/下跌/震荡）
2. 关键支撑位和阻力位
3. 技术指标解读（如果有RSI、MACD、EMA等数据）
4. 短期和中期走势预判

请用JSON格式回复:
{
    "recommendation": "bullish/bearish/neutral",
    "confidence": 0.0-1.0,
    "analysis": "详细分析文本",
    "key_points": ["观点1", "观点2"],
    "warnings": ["风险1", "风险2"]
}"""
        
        user_prompt = f"""分析 {symbol} 的技术面:

K线数据摘要:
{kline_summary}

技术指标:
{json.dumps(indicators, indent=2, ensure_ascii=False) if indicators else "暂无指标数据"}
"""
        
        response = await self._ask_ai(system_prompt, user_prompt)
        return self._parse_report(response)
    
    async def _get_kline_summary(self, symbol: str) -> str:
        """从数据库获取K线摘要"""
        try:
            async with AsyncSessionLocal() as db:
                summaries = []
                
                for interval in ["1d", "4h", "1h"]:
                    query = (
                        select(Kline)
                        .where(Kline.symbol == symbol)
                        .where(Kline.interval == interval)
                        .order_by(desc(Kline.open_time))
                        .limit(20)
                    )
                    result = await db.execute(query)
                    klines = list(reversed(result.scalars().all()))
                    
                    if klines:
                        latest = klines[-1]
                        earliest = klines[0]
                        highs = [float(k.high) for k in klines]
                        lows = [float(k.low) for k in klines]
                        closes = [float(k.close) for k in klines]
                        volumes = [float(k.volume) for k in klines]
                        
                        # 计算简单指标
                        avg_close = sum(closes) / len(closes)
                        price_change = ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] else 0
                        avg_volume = sum(volumes) / len(volumes)
                        latest_vol_ratio = volumes[-1] / avg_volume if avg_volume else 0
                        
                        summaries.append(
                            f"[{interval}周期 - 最近{len(klines)}根]\n"
                            f"  最新价: {float(latest.close):.2f}\n"
                            f"  区间最高: {max(highs):.2f}, 最低: {min(lows):.2f}\n"
                            f"  涨跌幅: {price_change:+.2f}%\n"
                            f"  均价: {avg_close:.2f}\n"
                            f"  最新成交量/均量比: {latest_vol_ratio:.2f}x"
                        )
                
                return "\n\n".join(summaries) if summaries else "暂无K线数据"
                
        except Exception as e:
            logger.error(f"[TechnicalAnalyst] 获取K线失败: {e}")
            return "K线数据获取失败"
    
    def _parse_report(self, response: str) -> AgentReport:
        """解析AI回复为报告"""
        try:
            # 尝试提取JSON
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            data = json.loads(json_str)
            
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=data.get("analysis", response),
                confidence=float(data.get("confidence", 0.5)),
                recommendation=data.get("recommendation", "neutral"),
                key_points=data.get("key_points", []),
                warnings=data.get("warnings", []),
            )
        except (json.JSONDecodeError, IndexError, KeyError):
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=response,
                confidence=0.5,
                recommendation="neutral",
            )


# ==================== Sentiment Analyst ====================

class SentimentAnalyst(BaseAgent):
    """
    📰 市场情绪分析师
    
    分析市场趋势、24h涨跌、成交量异动
    """
    
    def __init__(self, provider: BaseProvider):
        super().__init__("市场情绪分析师", "sentiment", provider)
    
    async def analyze(self, symbol: str, context: Dict[str, Any]) -> AgentReport:
        """基于市场数据分析情绪"""
        market = context.get("market", {})
        
        system_prompt = """你是一位加密货币市场情绪分析师。
你需要基于市场行情数据，判断当前市场情绪。

分析维度:
1. 24h价格变动幅度和方向
2. 成交量是否异常（放量/缩量）
3. 市场整体氛围（恐慌/贪婪/中性）
4. 短期动量信号

请用JSON格式回复:
{
    "recommendation": "bullish/bearish/neutral",
    "confidence": 0.0-1.0,
    "analysis": "详细分析文本",
    "key_points": ["观点1", "观点2"],
    "warnings": ["风险1", "风险2"]
}"""
        
        user_prompt = f"""分析 {symbol} 的市场情绪:

当前行情数据:
- 当前价格: {market.get('current_price', 'N/A')}
- 24h涨跌: {market.get('price_change_24h', 'N/A')}%
- 24h最高: {market.get('high_24h', 'N/A')}
- 24h最低: {market.get('low_24h', 'N/A')}
- 24h成交量: {market.get('volume_24h', 'N/A')}
"""
        
        response = await self._ask_ai(system_prompt, user_prompt)
        return self._parse_report(response)
    
    def _parse_report(self, response: str) -> AgentReport:
        """解析AI回复"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            data = json.loads(json_str)
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=data.get("analysis", response),
                confidence=float(data.get("confidence", 0.5)),
                recommendation=data.get("recommendation", "neutral"),
                key_points=data.get("key_points", []),
                warnings=data.get("warnings", []),
            )
        except (json.JSONDecodeError, IndexError, KeyError):
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=response,
                confidence=0.5,
                recommendation="neutral",
            )


# ==================== Risk Analyst ====================

class RiskAnalyst(BaseAgent):
    """
    ⚠️ 风控分析师
    
    分析仓位风险、资金占比、最大回撤
    """
    
    def __init__(self, provider: BaseProvider):
        super().__init__("风控分析师", "risk", provider)
    
    async def analyze(self, symbol: str, context: Dict[str, Any]) -> AgentReport:
        """基于持仓和钱包数据评估风险"""
        wallet = context.get("wallet", {})
        positions = context.get("positions", [])
        
        system_prompt = """你是一位加密货币风险管理专家。
你需要基于用户的持仓和资金情况，评估交易风险。

评估维度:
1. 资金利用率（已用/总额）
2. 单一币种集中度
3. 杠杆水平和爆仓风险
4. 建议的仓位大小和止损位置

请用JSON格式回复:
{
    "recommendation": "bullish/bearish/neutral",
    "confidence": 0.0-1.0,
    "analysis": "详细风险评估",
    "key_points": ["风险点1", "风险点2"],
    "warnings": ["严重风险1", "建议1"]
}"""
        
        # 格式化持仓信息
        position_text = "无持仓"
        if positions:
            lines = []
            for p in positions:
                lines.append(
                    f"  - {p.get('symbol', 'N/A')} {p.get('side', 'N/A')} "
                    f"数量:{p.get('size', 0)} 入场价:{p.get('entry_price', 0)} "
                    f"浮动盈亏:{p.get('unrealized_pnl', 0)} 杠杆:{p.get('leverage', 1)}x"
                )
            position_text = "\n".join(lines)
        
        user_prompt = f"""评估 {symbol} 相关交易的风险:

钱包状况:
- 总余额: {wallet.get('balance', 'N/A')} USDT
- 可用余额: {wallet.get('available', 'N/A')} USDT
- 冻结金额: {wallet.get('frozen', 'N/A')} USDT

当前持仓:
{position_text}
"""
        
        response = await self._ask_ai(system_prompt, user_prompt)
        return self._parse_report(response)
    
    def _parse_report(self, response: str) -> AgentReport:
        """解析AI回复"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            data = json.loads(json_str)
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=data.get("analysis", response),
                confidence=float(data.get("confidence", 0.5)),
                recommendation=data.get("recommendation", "neutral"),
                key_points=data.get("key_points", []),
                warnings=data.get("warnings", []),
            )
        except (json.JSONDecodeError, IndexError, KeyError):
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=response,
                confidence=0.5,
                recommendation="neutral",
            )


# ==================== Decision Maker ====================

class DecisionMaker(BaseAgent):
    """
    🧠 决策者
    
    汇总各分析师的报告，做出最终决策
    """
    
    def __init__(self, provider: BaseProvider):
        super().__init__("决策者", "decision_maker", provider)
    
    async def analyze(self, symbol: str, context: Dict[str, Any]) -> AgentReport:
        """不单独使用，由 synthesize 调用"""
        raise NotImplementedError("请使用 synthesize() 方法")
    
    async def synthesize(
        self,
        symbol: str,
        reports: List[AgentReport],
        debate_history: Optional[List[str]] = None,
    ) -> AgentReport:
        """汇总各智能体报告，输出最终决策"""
        
        system_prompt = """你是一位资深交易决策者。
多位分析师已经从不同角度分析了当前市场，你需要:

1. 综合所有分析师的观点
2. 识别一致性意见和分歧点
3. 权衡不同维度的重要性
4. 给出最终的交易建议

请用JSON格式回复:
{
    "recommendation": "bullish/bearish/neutral",
    "confidence": 0.0-1.0,
    "analysis": "综合决策分析",
    "key_points": ["关键结论1", "关键结论2"],
    "warnings": ["需注意的风险"]
}"""
        
        # 格式化各分析师报告
        reports_text = ""
        for r in reports:
            reports_text += f"\n{'='*40}\n"
            reports_text += f"📊 {r.agent_name} ({r.role})\n"
            reports_text += f"建议: {r.recommendation} (信心: {r.confidence:.0%})\n"
            reports_text += f"分析: {r.analysis}\n"
            if r.key_points:
                reports_text += f"关键观点: {', '.join(r.key_points)}\n"
            if r.warnings:
                reports_text += f"⚠️ 风险提示: {', '.join(r.warnings)}\n"
        
        user_prompt = f"""请综合以下分析师的报告，对 {symbol} 做出最终决策:

{reports_text}
"""
        
        if debate_history:
            user_prompt += f"\n辩论历史:\n" + "\n".join(debate_history)
        
        response = await self._ask_ai(system_prompt, user_prompt)
        return self._parse_report(response)
    
    def _parse_report(self, response: str) -> AgentReport:
        """解析AI回复"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            data = json.loads(json_str)
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=data.get("analysis", response),
                confidence=float(data.get("confidence", 0.5)),
                recommendation=data.get("recommendation", "neutral"),
                key_points=data.get("key_points", []),
                warnings=data.get("warnings", []),
            )
        except (json.JSONDecodeError, IndexError, KeyError):
            return AgentReport(
                agent_name=self.name,
                role=self.role,
                analysis=response,
                confidence=0.5,
                recommendation="neutral",
            )


# ==================== Orchestrator ====================

class MultiAgentOrchestrator:
    """
    🎯 多智能体编排器
    
    协调各智能体的分析流程:
    1. 并行调用 3 个分析师
    2. 可选辩论轮次
    3. 决策者汇总输出
    """
    
    def __init__(self, provider: BaseProvider):
        self.provider = provider
        self.technical = TechnicalAnalyst(provider)
        self.sentiment = SentimentAnalyst(provider)
        self.risk = RiskAnalyst(provider)
        self.decision_maker = DecisionMaker(provider)
    
    async def run(
        self,
        symbol: str,
        context: Dict[str, Any],
        debate_rounds: int = 0,
    ) -> MultiAgentResult:
        """
        运行多智能体分析流程
        
        Args:
            symbol: 交易对
            context: 上下文（market, wallet, positions, indicators）
            debate_rounds: 辩论轮数（0=不辩论，直接汇总）
        """
        import asyncio
        
        logger.info(f"[MultiAgent] 开始分析 {symbol}, 辩论轮数={debate_rounds}")
        
        # Step 1: 并行调用 3 个分析师
        results = await asyncio.gather(
            self._safe_analyze(self.technical, symbol, context),
            self._safe_analyze(self.sentiment, symbol, context),
            self._safe_analyze(self.risk, symbol, context),
        )
        reports = [r for r in results if r is not None]
        
        logger.info(f"[MultiAgent] {len(reports)}/3 个分析师完成分析")
        
        # Step 2: 可选辩论（让分析师互相质疑）
        debate_history = []
        for round_num in range(debate_rounds):
            logger.info(f"[MultiAgent] 辩论第 {round_num + 1} 轮")
            debate_round = await self._debate_round(symbol, reports, round_num + 1)
            debate_history.append(debate_round)
            # 用辩论结果更新各分析师的分析
            for i, report in enumerate(reports):
                report.analysis += f"\n[辩论第{round_num+1}轮补充] {debate_round}"
        
        # Step 3: 决策者汇总
        final_report = await self.decision_maker.synthesize(
            symbol, reports, debate_history if debate_history else None
        )
        
        # 构建最终结果
        result = MultiAgentResult(
            symbol=symbol,
            reports=reports,
            final_decision=final_report.analysis,
            final_recommendation=final_report.recommendation,
            confidence=final_report.confidence,
            reasoning=final_report.analysis,
            warnings=final_report.warnings,
            debate_rounds=debate_rounds,
        )
        
        # 合并所有分析师的风险提示
        for r in reports:
            result.warnings.extend(r.warnings)
        result.warnings = list(set(result.warnings))  # 去重
        
        logger.info(
            f"[MultiAgent] ✅ 分析完成: {symbol} → "
            f"{result.final_recommendation} (信心: {result.confidence:.0%})"
        )
        
        return result
    
    async def _safe_analyze(
        self, agent: BaseAgent, symbol: str, context: Dict[str, Any]
    ) -> Optional[AgentReport]:
        """安全调用分析师（捕获异常）"""
        try:
            return await agent.analyze(symbol, context)
        except Exception as e:
            logger.error(f"[MultiAgent] {agent.name} 分析失败: {e}")
            return AgentReport(
                agent_name=agent.name,
                role=agent.role,
                analysis=f"分析失败: {str(e)}",
                confidence=0.0,
                recommendation="neutral",
                warnings=[f"{agent.name}分析失败，结果可能不完整"],
            )
    
    async def _debate_round(
        self, symbol: str, reports: List[AgentReport], round_num: int
    ) -> str:
        """执行一轮辩论"""
        # 让各分析师看到其他分析师的观点并提出质疑
        other_views = ""
        for r in reports:
            other_views += f"- {r.agent_name}: {r.recommendation} ({r.confidence:.0%}) - {r.analysis[:200]}\n"
        
        messages = [
            ChatMessage(
                role="system",
                content="你是一位交易分析辩论主持人。请基于各分析师的观点，指出潜在的分歧和需要深入讨论的点。简洁明了，不超过200字。"
            ),
            ChatMessage(
                role="user",
                content=f"第{round_num}轮辩论 - {symbol}\n各方观点:\n{other_views}\n请指出分歧点和需要关注的问题。"
            ),
        ]
        
        try:
            response = await self.provider.chat(messages, temperature=0.5, max_tokens=500)
            return response.content
        except Exception as e:
            return f"辩论失败: {str(e)}"
