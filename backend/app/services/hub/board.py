"""
Hub Board — 董事会辩论模块
===============================
多 AI 智能体辩论 → 投票 → 共识 → 执行

职责:
- 并发调用所有 active Agent
- 收集每个 Agent 的独立决策
- 投票 → 多数派共识
- 若共识 != hold → 通过 Pipeline 执行

与 Pipeline 的关系:
- 共识结果通过 Pipeline.submit_order() 执行
- 仍然经过 Risk → Execution 流程
"""

import json
import asyncio
from decimal import Decimal
from typing import List, Dict, Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hub_agent import HubAgent
from app.core.time_utils import utc_now


BOARD_PROMPT_TEMPLATE = """## 董事会辩论

议题: {topic}
交易对: {symbol}

你是董事会中的一名 AI 顾问。请独立分析并给出你的交易建议。

请先调用以下工具获取数据:
1. get_price(symbol="{symbol}") — 获取实时价格
2. get_indicators(symbol="{symbol}") — 获取技术指标

然后严格输出以下 JSON 格式 (无其他内容):
```json
{{
  "decision": "open_long" | "open_short" | "hold",
  "confidence": 0.0 ~ 1.0,
  "reasoning": "你的分析理由 (2-3 句话)"
}}
```"""


class HubBoard:
    """
    董事会辩论
    
    多个 AI 智能体独立分析 → 汇总 → 投票共识 → 执行
    """
    
    async def deliberate(
        self,
        agents: List[HubAgent],
        topic: str,
        symbol: str,
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """
        执行一次董事会辩论
        
        Returns:
            {
                "opinions": [...],
                "consensus": {...},
            }
        """
        from app.services.hub.brain import hub_brain
        
        prompt = BOARD_PROMPT_TEMPLATE.format(topic=topic, symbol=symbol)
        
        # 并发调用所有 Agent
        tasks = []
        for agent in agents:
            tasks.append(self._get_opinion(hub_brain, agent, prompt, db, user_id))
        
        raw_opinions = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 解析结果
        opinions = []
        for i, (agent, result) in enumerate(zip(agents, raw_opinions)):
            if isinstance(result, Exception):
                opinions.append({
                    "agent_id": agent.id,
                    "agent_name": agent.name,
                    "avatar": agent.avatar,
                    "decision": "hold",
                    "confidence": 0.0,
                    "reasoning": f"[错误] {str(result)[:200]}",
                })
            else:
                opinion = result
                opinion["agent_id"] = agent.id
                opinion["agent_name"] = agent.name
                opinion["avatar"] = agent.avatar
                opinions.append(opinion)
        
        # 投票
        consensus = self._vote(opinions)
        
        # 如果共识需要交易, 执行
        if consensus["decision"] != "hold" and consensus["confidence"] >= 0.5:
            execution_result = await self._execute_consensus(
                consensus, symbol, db, user_id,
            )
            consensus["executed"] = execution_result.get("success", False)
            consensus["order_id"] = execution_result.get("order_id")
        else:
            consensus["executed"] = False
            consensus["order_id"] = None
        
        logger.info(
            f"[HubBoard] 辩论完成: {len(opinions)} 个意见, "
            f"共识={consensus['decision']}, 执行={consensus['executed']}"
        )
        
        return {
            "opinions": opinions,
            "consensus": consensus,
        }
    
    async def _get_opinion(
        self,
        brain,
        agent: HubAgent,
        prompt: str,
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """获取单个 Agent 的独立观点"""
        reply = await brain.chat_once(
            agent=agent,
            message=prompt,
            db=db,
            user_id=user_id,
        )
        
        # 解析 JSON
        return self._parse_opinion(reply)
    
    def _parse_opinion(self, reply: str) -> dict:
        """从 AI 回复中解析结构化观点"""
        import re
        
        # 尝试提取 JSON
        try:
            return json.loads(reply)
        except json.JSONDecodeError:
            pass
        
        # 从 ```json ... ``` 中提取
        json_match = re.search(r'```json\s*\n?(.*?)\n?\s*```', reply, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 从 { ... } 中提取
        brace_match = re.search(r'\{[^{}]*"decision"[^{}]*\}', reply, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        # 兜底: 关键词匹配
        decision = "hold"
        if any(kw in reply.lower() for kw in ["open_long", "做多", "买入"]):
            decision = "open_long"
        elif any(kw in reply.lower() for kw in ["open_short", "做空", "卖出"]):
            decision = "open_short"
        
        return {
            "decision": decision,
            "confidence": 0.3,
            "reasoning": reply[:200],
        }
    
    def _vote(self, opinions: List[dict]) -> dict:
        """投票: 统计多数派"""
        vote_count = {"open_long": 0, "open_short": 0, "hold": 0}
        confidence_sum = {"open_long": 0.0, "open_short": 0.0, "hold": 0.0}
        
        for op in opinions:
            d = op.get("decision", "hold")
            c = float(op.get("confidence", 0))
            if d in vote_count:
                vote_count[d] += 1
                confidence_sum[d] += c
        
        # 找多数派
        winner = max(vote_count, key=vote_count.get)
        winner_count = vote_count[winner]
        total = len(opinions)
        
        avg_confidence = (
            confidence_sum[winner] / winner_count
            if winner_count > 0 else 0
        )
        
        # 构建投票描述
        vote_parts = []
        label_map = {"open_long": "做多", "open_short": "做空", "hold": "观望"}
        for d, count in vote_count.items():
            if count > 0:
                vote_parts.append(f"{label_map.get(d, d)}:{count}")
        
        return {
            "decision": winner,
            "confidence": round(avg_confidence, 2),
            "vote_count": f"{' / '.join(vote_parts)} (共{total}票)",
        }
    
    async def _execute_consensus(
        self,
        consensus: dict,
        symbol: str,
        db: AsyncSession,
        user_id: int,
    ) -> dict:
        """执行共识决策 (直接通过 OrderExecutor，绕过 Pipeline)"""
        from app.services.trading import OrderExecutor
        from app.models.wallet import Wallet
        from app.models.order import OrderSide, OrderType
        from app.core.risk_config import risk_config
        
        try:
            # 获取余额
            result = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallet = result.scalar_one_or_none()
            if not wallet:
                return {"success": False, "error": "钱包不存在"}
            
            available_balance = Decimal(str(wallet.balance))
            
            # 读取风控配置
            config = risk_config.load_for_user(user_id)
            risk_pct = config.get("risk_percent", 10.0)
            leverage = config.get("default_leverage", 5)
            sl_pct = config.get("default_sl_pct", 2.0)
            tp_pct = config.get("default_tp_pct", 4.0)
            
            # 计算下单数量
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            ticker = await client.get_ticker(symbol)
            current_price = Decimal(str(ticker.get("lastPrice", 0))) if ticker else Decimal("0")
            
            if current_price <= 0:
                return {"success": False, "error": "无法获取价格"}
            
            position_value = available_balance * Decimal(str(risk_pct / 100))
            quantity = (position_value * leverage) / current_price
            
            side_str = "buy" if consensus["decision"] == "open_long" else "sell"
            order_side = OrderSide(side_str)
            
            # 自动 TP/SL
            if side_str == "buy":
                sl = (current_price * (1 - Decimal(str(sl_pct)) / 100)).quantize(Decimal("0.01"))
                tp = (current_price * (1 + Decimal(str(tp_pct)) / 100)).quantize(Decimal("0.01"))
            else:
                sl = (current_price * (1 + Decimal(str(sl_pct)) / 100)).quantize(Decimal("0.01"))
                tp = (current_price * (1 - Decimal(str(tp_pct)) / 100)).quantize(Decimal("0.01"))
            
            order = await OrderExecutor.create_order(
                db=db,
                user_id=user_id,
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                leverage=leverage,
                stop_loss=sl,
                take_profit=tp,
                note=f"[董事会共识] {consensus.get('vote_count', '')}",
            )
            
            return {"success": True, "order_id": order.id}
            
        except Exception as e:
            logger.error(f"[HubBoard] Execute consensus failed: {e}")
            return {"success": False, "error": str(e)}


# 全局单例
hub_board = HubBoard()
