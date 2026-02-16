"""
AI Trader — 自主交易机器人
===========================
不依赖任何预定义规则, 完全由 AI 自主决策:

工作流:
1. 定时收集市场数据 (价格/K线/技术指标)
2. 读取账户状态 (余额/持仓)
3. 加载历史交易经验 (记忆)
4. AI 综合分析 → 产出结构化决策
5. 风控检查 → 执行或拒绝
6. 完整记录决策思维链
7. 交易结束后 → AI 反思 → 存入记忆库 → 进化

扩展点:
- 预留 news_context 字段, 未来接入新闻 API
- 预留 sentiment_context 字段, 未来接入市场情绪
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.ai_trader import AITraderDecision, AITraderConfig
from app.models.order import Order, OrderSide, OrderType, OrderStatus
from app.models.position import Position, PositionStatus
from app.models.wallet import Wallet
from app.models.strategy import TradeMemory
from app.services.trading import OrderExecutor
from app.services.quant.risk_guard import RiskGuard
from app.services.quant.indicators import calculate_all_indicators
from app.services.ai.brain import AIBrain
from app.services.ai.providers import ChatMessage


# ============================================================
# 决策频率映射
# ============================================================
INTERVAL_SECONDS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
}


# ============================================================
# AI 决策 Prompt
# ============================================================
AI_TRADER_SYSTEM_PROMPT = """你是一位经验丰富的加密货币交易员。你独立分析市场并做出交易决策。

## 你的核心能力
- 趋势判断: 通过多重技术指标判断当前趋势方向和强度
- 时机选择: 在最优入/出场点操作
- 风险管理: 合理的仓位控制和止损设置
- 从过去经验中学习, 避免重蹈覆辙

## 决策原则
1. **不轻易出手** — 只在高确信度信号出现时行动, 观望也是好决策
2. **顺势而为** — 不逆趋势操作, 除非有明确反转信号
3. **控制风险** — 每笔交易严格设置止损止盈
4. **经验驱动** — 认真参考历史交易的经验教训
5. **资金管理** — 不要把所有钱一次投入, 保留灵活性

## 重要约束
- 最大单笔仓位: 可用余额的 {max_position_pct}%
- 最大杠杆: {max_leverage}x
- 没把握时选 hold (观望), 不要强行交易

## 你必须返回 JSON 格式:
```json
{{
  "action": "hold",
  "reasoning": "详细的思考过程: 我观察到什么, 我分析了什么, 我的判断依据是什么...",
  "confidence": 0.0,
  "symbol": "BTCUSDT",
  "side": "buy",
  "position_pct": 0,
  "leverage": 1,
  "stop_loss_pct": 0,
  "take_profit_pct": 0,
  "sl_reason": "止损理由",
  "tp_reason": "止盈理由"
}}
```

action 可选值:
- `hold` — 观望, 当前不适合交易 (此时其他字段不需要填)
- `open_long` — 开多 (看涨)
- `open_short` — 开空 (看跌)
- `close` — 平仓 (对当前持仓)
- `add_position` — 加仓

reasoning 要求 (这是最重要的字段！):
- 至少 100 字
- 包含: 市场趋势分析, 关键指标解读, 入场/离场理由
- 如果参考了历史经验, 说明参考了哪条, 为什么
- 如果选择 hold, 说明为什么当前不适合交易
"""

AI_TRADER_USER_PROMPT = """当前时间: {timestamp}

📊 市场数据 ({symbol}):
{market_data}

💰 账户状态:
{account_data}

📈 持仓信息:
{position_data}

📚 历史交易经验 (你之前学到的教训):
{experience_data}

{extra_context}

请分析以上数据, 做出你的交易决策。返回 JSON。"""


# ============================================================
# 核心引擎
# ============================================================
class AITrader:
    """
    AI 自主交易引擎

    像一个真正的交易员:
    - 不依赖规则, 自己分析决策
    - 记录每一个决策的完整思考过程
    - 交易后反思, 积累经验
    - 用经验指导未来决策 → 不断进化
    """

    def __init__(self):
        self.risk_guard = RiskGuard()
        self._running = False
        self._tasks: Dict[int, asyncio.Task] = {}  # user_id -> task

    # ============================================================
    # 生命周期
    # ============================================================
    async def start(self, user_id: int):
        """启动某用户的 AI Trader"""
        if user_id in self._tasks:
            logger.warning(f"[AITrader] User {user_id} already running")
            return

        self._running = True
        task = asyncio.create_task(self._user_loop(user_id))
        self._tasks[user_id] = task
        logger.info(f"[AITrader] ✅ Started for user {user_id}")

    async def stop(self, user_id: int):
        """停止某用户的 AI Trader"""
        if user_id in self._tasks:
            self._tasks[user_id].cancel()
            del self._tasks[user_id]
            logger.info(f"[AITrader] ⏹ Stopped for user {user_id}")

    async def stop_all(self):
        """停止所有"""
        for uid in list(self._tasks.keys()):
            await self.stop(uid)

    def is_running(self, user_id: int) -> bool:
        """检查某用户是否在运行"""
        return user_id in self._tasks and not self._tasks[user_id].done()

    # ============================================================
    # 主循环
    # ============================================================
    async def _user_loop(self, user_id: int):
        """单个用户的 AI Trader 运行循环"""
        logger.info(f"[AITrader] Entering loop for user {user_id}")

        while self._running:
            try:
                async with AsyncSessionLocal() as db:
                    # 读取配置
                    config = await self._get_config(db, user_id)
                    if not config or not config.enabled:
                        logger.info(f"[AITrader] User {user_id} disabled, stopping")
                        break

                    interval_sec = INTERVAL_SECONDS.get(config.interval, 900)
                    symbols = config.symbols or ["BTCUSDT"]

                    # 对每个交易对运行决策周期
                    for symbol in symbols:
                        try:
                            await self.run_cycle(db, user_id, symbol, config)
                        except Exception as e:
                            logger.error(
                                f"[AITrader] Cycle error for {symbol}: {e}"
                            )

                    await db.commit()

                # 等待下一个周期
                logger.info(
                    f"[AITrader] User {user_id}: sleeping {interval_sec}s "
                    f"until next cycle"
                )
                await asyncio.sleep(interval_sec)

            except asyncio.CancelledError:
                logger.info(f"[AITrader] User {user_id} loop cancelled")
                break
            except Exception as e:
                logger.error(f"[AITrader] Loop error: {e}")
                await asyncio.sleep(60)  # 出错后等 1 分钟重试

    # ============================================================
    # 决策周期 (核心)
    # ============================================================
    async def run_cycle(
        self,
        db: AsyncSession,
        user_id: int,
        symbol: str,
        config: AITraderConfig,
    ):
        """
        一个完整的 AI 决策周期

        1. 收集市场数据
        2. 读取账户状态
        3. 加载历史经验
        4. AI 决策
        5. 风控检查
        6. 执行交易
        7. 记录决策
        """
        logger.info(f"[AITrader] ▶ Starting cycle: user={user_id}, {symbol}")

        # 获取周期编号
        cycle_no = await self._get_next_cycle_no(db, user_id)

        # 1. 收集市场数据
        market_data = await self._gather_market_data(symbol)
        if not market_data:
            logger.warning(f"[AITrader] Cannot gather market data for {symbol}")
            return

        # 2. 读取账户状态
        account_data = await self._gather_account_state(db, user_id)

        # 3. 读取当前持仓
        positions = await self._get_open_positions(db, user_id, symbol)

        # 4. 加载历史经验
        memories = await self._load_trade_memories(db, user_id, symbol)

        # 5. AI 决策
        decision = await self._ai_decide(
            db, user_id, symbol, config,
            market_data, account_data, positions, memories,
        )

        if not decision:
            logger.warning(f"[AITrader] AI returned no valid decision")
            return

        # 6. 处理决策
        order_id = None
        executed = False
        reject_reason = None

        if decision["action"] == "hold":
            reject_reason = "AI 选择观望"
            logger.info(f"[AITrader] 📊 HOLD — {decision.get('reasoning', '')[:80]}")

        elif decision["action"] in ("open_long", "open_short", "add_position"):
            # 风控检查
            risk_ok, risk_msg = await self._risk_check(
                db, user_id, decision, account_data, positions, config,
            )

            if not risk_ok:
                reject_reason = f"风控拒绝: {risk_msg}"
                logger.warning(f"[AITrader] 🛡️ Risk rejected: {risk_msg}")

            elif decision.get("confidence", 0) < config.min_confidence:
                reject_reason = (
                    f"信心不足: {decision.get('confidence', 0):.0%} "
                    f"< {config.min_confidence:.0%}"
                )
                logger.info(f"[AITrader] ⏸ Low confidence, skipping")

            else:
                # 执行交易
                order_id = await self._execute_open(
                    db, user_id, symbol, decision, account_data, config,
                )
                executed = order_id is not None
                if executed:
                    logger.info(
                        f"[AITrader] ✅ EXECUTED: {decision['action']} "
                        f"{symbol} order_id={order_id}"
                    )

        elif decision["action"] == "close":
            # 平仓逻辑
            if positions:
                order_id = await self._execute_close(
                    db, user_id, symbol, positions, decision,
                )
                executed = order_id is not None
            else:
                reject_reason = "无持仓可平"

        # 7. 保存决策记录
        await self._save_decision(
            db, user_id, symbol, cycle_no,
            decision, market_data, account_data, memories,
            executed, order_id, reject_reason,
        )

        await db.commit()
        logger.info(
            f"[AITrader] ◀ Cycle {cycle_no} done: {decision['action']} "
            f"{'✅' if executed else '⏸'}"
        )

    # ============================================================
    # 数据收集
    # ============================================================
    async def _gather_market_data(self, symbol: str) -> Optional[Dict]:
        """收集市场数据: 价格 + K线 + 技术指标"""
        try:
            from app.services.exchange import BinanceClient
            client = BinanceClient()

            # 获取实时价格
            ticker = await client.get_ticker(symbol)
            if not ticker:
                return None

            current_price = float(ticker.get("lastPrice", 0))
            price_change = float(ticker.get("priceChangePercent", 0))
            high_24h = float(ticker.get("highPrice", 0))
            low_24h = float(ticker.get("lowPrice", 0))
            volume_24h = float(ticker.get("quoteVolume", 0))

            # 获取 K 线
            klines = await client.get_klines(symbol, "1h", limit=200)

            # 计算技术指标
            indicators = {}
            if klines:
                indicators = calculate_all_indicators(klines)

            return {
                "current_price": current_price,
                "price_change_24h": price_change,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "volume_24h": volume_24h,
                "indicators": indicators,
                "klines_count": len(klines) if klines else 0,
            }

        except Exception as e:
            logger.error(f"[AITrader] Market data error: {e}")
            return None

    async def _gather_account_state(
        self, db: AsyncSession, user_id: int
    ) -> Dict:
        """收集账户状态"""
        result = {
            "balance": 0.0,
            "available": 0.0,
            "frozen": 0.0,
            "today_pnl": 0.0,
            "today_trades": 0,
        }

        try:
            # 钱包
            wallet_result = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id)
            )
            wallet = wallet_result.scalar_one_or_none()
            if wallet:
                result["balance"] = float(wallet.balance)
                result["available"] = float(wallet.balance)
                result["frozen"] = float(wallet.frozen)

            # 今日交易统计
            today = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            orders_result = await db.execute(
                select(func.count(Order.id)).where(
                    Order.user_id == user_id,
                    Order.created_at >= today,
                    Order.status == OrderStatus.FILLED,
                )
            )
            result["today_trades"] = orders_result.scalar() or 0

        except Exception as e:
            logger.error(f"[AITrader] Account state error: {e}")

        return result

    async def _get_open_positions(
        self, db: AsyncSession, user_id: int, symbol: str
    ) -> List[Dict]:
        """获取当前持仓"""
        try:
            result = await db.execute(
                select(Position).where(
                    Position.user_id == user_id,
                    Position.symbol == symbol,
                    Position.status == PositionStatus.OPEN,
                )
            )
            positions = result.scalars().all()
            return [
                {
                    "id": p.id,
                    "side": p.side.value,
                    "size": float(p.size),
                    "entry_price": float(p.entry_price),
                    "leverage": p.leverage,
                    "unrealized_pnl": float(p.unrealized_pnl)
                    if p.unrealized_pnl else 0,
                    "stop_loss": float(p.stop_loss) if p.stop_loss else None,
                    "take_profit": float(p.take_profit) if p.take_profit else None,
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"[AITrader] Positions error: {e}")
            return []

    async def _load_trade_memories(
        self, db: AsyncSession, user_id: int, symbol: str, limit: int = 10
    ) -> List[Dict]:
        """加载历史交易经验 (反思记忆)"""
        try:
            result = await db.execute(
                select(TradeMemory)
                .where(
                    TradeMemory.user_id == user_id,
                    TradeMemory.symbol == symbol,
                )
                .order_by(desc(TradeMemory.created_at))
                .limit(limit)
            )
            memories = result.scalars().all()
            return [
                {
                    "symbol": m.symbol,
                    "side": m.side,
                    "pnl_pct": float(m.pnl_pct) if m.pnl_pct else 0,
                    "open_reason": m.open_reason or "",
                    "close_reason": m.close_reason or "",
                    "lesson": m.lesson or "",
                    "created_at": m.created_at.isoformat()
                    if m.created_at else "",
                }
                for m in memories
            ]
        except Exception as e:
            logger.error(f"[AITrader] Load memories error: {e}")
            return []

    # ============================================================
    # AI 决策 (核心)
    # ============================================================
    async def _ai_decide(
        self,
        db: AsyncSession,
        user_id: int,
        symbol: str,
        config: AITraderConfig,
        market_data: Dict,
        account_data: Dict,
        positions: List[Dict],
        memories: List[Dict],
    ) -> Optional[Dict]:
        """
        让 AI 分析数据并做出交易决策

        这是整个系统的核心 —— AI 完全自主判断
        """
        try:
            provider = await AIBrain.get_provider(db, user_id)

            # 构建 system prompt
            system_prompt = AI_TRADER_SYSTEM_PROMPT.format(
                max_position_pct=config.max_position_pct,
                max_leverage=config.max_leverage,
            )

            # 构建 user prompt
            user_prompt = AI_TRADER_USER_PROMPT.format(
                timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                symbol=symbol,
                market_data=self._format_market_data(market_data),
                account_data=self._format_account_data(account_data),
                position_data=self._format_positions(positions),
                experience_data=self._format_memories(memories),
                extra_context="",  # 预留: 未来的新闻 / 情绪数据
            )

            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ]

            logger.info(f"[AITrader] 🧠 Calling AI for {symbol}...")
            response = await provider.chat(
                messages=messages,
                temperature=0.3,  # 低温度 = 更确定性的决策
                max_tokens=2000,
            )

            # 解析 JSON 决策
            decision = self._parse_decision(response.content)
            if decision:
                logger.info(
                    f"[AITrader] Decision: {decision['action']} "
                    f"conf={decision.get('confidence', 0):.0%}"
                )
            return decision

        except Exception as e:
            logger.error(f"[AITrader] AI decide error: {e}")
            return None

    def _parse_decision(self, raw: str) -> Optional[Dict]:
        """解析 AI 返回的 JSON 决策"""
        # 尝试提取 JSON 块
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            # 尝试 ```json ``` 格式
            json_match = re.search(
                r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL
            )
            if json_match:
                json_str = json_match.group(1)
            else:
                logger.warning(f"[AITrader] No JSON found in response")
                return None
        else:
            json_str = json_match.group()

        try:
            data = json.loads(json_str)

            # 验证必要字段
            action = data.get("action", "hold").lower()
            valid_actions = {
                "hold", "open_long", "open_short", "close", "add_position"
            }
            if action not in valid_actions:
                action = "hold"

            return {
                "action": action,
                "reasoning": data.get("reasoning", "无思考过程"),
                "confidence": float(data.get("confidence", 0)),
                "symbol": data.get("symbol", "BTCUSDT"),
                "side": data.get("side", "buy"),
                "position_pct": float(data.get("position_pct", 0)),
                "leverage": int(data.get("leverage", 1)),
                "stop_loss_pct": float(data.get("stop_loss_pct", 0)),
                "take_profit_pct": float(data.get("take_profit_pct", 0)),
                "sl_reason": data.get("sl_reason", ""),
                "tp_reason": data.get("tp_reason", ""),
            }

        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"[AITrader] JSON parse error: {e}")
            return None

    # ============================================================
    # 风控检查
    # ============================================================
    async def _risk_check(
        self,
        db: AsyncSession,
        user_id: int,
        decision: Dict,
        account_data: Dict,
        positions: List[Dict],
        config: AITraderConfig,
    ) -> Tuple[bool, str]:
        """风控检查 — AI 也不能绕过"""
        try:
            balance = account_data.get("balance", 0)
            if balance <= 0:
                return False, "余额为零"

            # 使用 RiskGuard 检查
            side = "buy" if "long" in decision["action"] else "sell"
            position_pct = min(
                decision.get("position_pct", 30),
                config.max_position_pct
            )
            leverage = min(
                decision.get("leverage", 1),
                config.max_leverage
            )

            all_passed, results = self.risk_guard.check_all(
                signal_side=side,
                symbol=decision.get("symbol", "BTCUSDT"),
                position_pct=position_pct,
                leverage=leverage,
                stop_loss_pct=decision.get("stop_loss_pct", 2.0),
                take_profit_pct=decision.get("take_profit_pct", 4.0),
                wallet_balance=balance,
                open_positions=positions,
                today_trades=account_data.get("today_trades", 0),
                today_pnl=account_data.get("today_pnl", 0),
            )

            if not all_passed:
                failed = [r for r in results if not r.passed]
                reasons = "; ".join([f"{r.rule}: {r.reason}" for r in failed])
                return False, reasons

            return True, ""

        except Exception as e:
            logger.error(f"[AITrader] Risk check error: {e}")
            return False, f"风控异常: {str(e)}"

    # ============================================================
    # 执行交易
    # ============================================================
    async def _execute_open(
        self,
        db: AsyncSession,
        user_id: int,
        symbol: str,
        decision: Dict,
        account_data: Dict,
        config: AITraderConfig,
    ) -> Optional[int]:
        """执行开仓"""
        try:
            from app.services.exchange import BinanceClient
            client = BinanceClient()

            # 获取当前价格
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker.get("lastPrice", 0)) if ticker else 0
            if current_price <= 0:
                return None

            # 计算参数
            balance = account_data.get("balance", 0)
            position_pct = min(
                decision.get("position_pct", 30),
                config.max_position_pct
            ) / 100.0
            leverage = min(
                decision.get("leverage", 1),
                config.max_leverage
            )

            margin = balance * position_pct
            notional = margin * leverage
            quantity = notional / current_price

            # 精度处理
            quantity = round(quantity, 6)
            if quantity <= 0:
                return None

            # 止损止盈
            side = OrderSide.BUY if "long" in decision["action"] else OrderSide.SELL
            sl_pct = decision.get("stop_loss_pct", 2.0) / 100.0
            tp_pct = decision.get("take_profit_pct", 4.0) / 100.0

            if side == OrderSide.BUY:
                stop_loss = Decimal(str(round(
                    current_price * (1 - sl_pct), 2
                ))) if sl_pct > 0 else None
                take_profit = Decimal(str(round(
                    current_price * (1 + tp_pct), 2
                ))) if tp_pct > 0 else None
            else:
                stop_loss = Decimal(str(round(
                    current_price * (1 + sl_pct), 2
                ))) if sl_pct > 0 else None
                take_profit = Decimal(str(round(
                    current_price * (1 - tp_pct), 2
                ))) if tp_pct > 0 else None

            # 通过统一的 OrderExecutor 下单
            order = await OrderExecutor.create_order(
                db=db,
                user_id=user_id,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=Decimal(str(quantity)),
                leverage=leverage,
                stop_loss=stop_loss,
                take_profit=take_profit,
                note=f"[AITrader] {decision['action']} "
                     f"conf={decision.get('confidence', 0):.0%}",
            )

            return order.id

        except Exception as e:
            logger.error(f"[AITrader] Execute open error: {e}")
            return None

    async def _execute_close(
        self,
        db: AsyncSession,
        user_id: int,
        symbol: str,
        positions: List[Dict],
        decision: Dict,
    ) -> Optional[int]:
        """执行平仓"""
        try:
            from app.services.trading import PositionManager

            for pos in positions:
                from app.services.exchange import BinanceClient
                client = BinanceClient()
                ticker = await client.get_ticker(symbol)
                close_price = (
                    Decimal(str(ticker.get("lastPrice", 0)))
                    if ticker else Decimal("0")
                )

                position, pnl = await PositionManager.close_position(
                    db=db,
                    position_id=pos["id"],
                    close_price=close_price,
                )
                return pos["id"]

            return None

        except Exception as e:
            logger.error(f"[AITrader] Execute close error: {e}")
            return None

    # ============================================================
    # 记录决策
    # ============================================================
    async def _save_decision(
        self,
        db: AsyncSession,
        user_id: int,
        symbol: str,
        cycle_no: int,
        decision: Dict,
        market_data: Dict,
        account_data: Dict,
        memories: List[Dict],
        executed: bool,
        order_id: Optional[int],
        reject_reason: Optional[str],
    ):
        """保存完整的 AI 决策记录"""
        # 构建精简的市场快照 (不存完整K线, 太大)
        market_snapshot = {
            "price": market_data.get("current_price"),
            "change_24h": market_data.get("price_change_24h"),
            "high_24h": market_data.get("high_24h"),
            "low_24h": market_data.get("low_24h"),
        }

        indicators = market_data.get("indicators", {})
        if indicators:
            market_snapshot["rsi"] = indicators.get("rsi")
            macd = indicators.get("macd", {})
            if isinstance(macd, dict):
                market_snapshot["macd_histogram"] = macd.get("histogram")
            market_snapshot["atr"] = indicators.get("atr")

        record = AITraderDecision(
            user_id=user_id,
            symbol=symbol,
            cycle_no=cycle_no,
            action=decision.get("action", "hold"),
            reasoning=decision.get("reasoning", ""),
            confidence=decision.get("confidence", 0),
            market_snapshot=market_snapshot,
            account_snapshot=account_data,
            experience_used=(
                {"memories": [m.get("lesson", "") for m in memories[:5]]}
                if memories else None
            ),
            risk_params={
                "position_pct": decision.get("position_pct"),
                "leverage": decision.get("leverage"),
                "stop_loss_pct": decision.get("stop_loss_pct"),
                "take_profit_pct": decision.get("take_profit_pct"),
                "sl_reason": decision.get("sl_reason"),
                "tp_reason": decision.get("tp_reason"),
            } if decision.get("action") != "hold" else None,
            executed=executed,
            order_id=order_id,
            reject_reason=reject_reason,
        )
        db.add(record)

    # ============================================================
    # 格式化函数
    # ============================================================
    def _format_market_data(self, data: Dict) -> str:
        """格式化市场数据给 AI 阅读"""
        lines = [
            f"  当前价格: ${data.get('current_price', 0):,.2f}",
            f"  24h涨跌: {data.get('price_change_24h', 0):+.2f}%",
            f"  24h高: ${data.get('high_24h', 0):,.2f}",
            f"  24h低: ${data.get('low_24h', 0):,.2f}",
            f"  24h成交额: ${data.get('volume_24h', 0):,.0f}",
        ]

        indicators = data.get("indicators", {})
        if indicators:
            lines.append("")
            lines.append("  技术指标:")

            rsi = indicators.get("rsi")
            if rsi:
                status = "(超买)" if rsi > 70 else "(超卖)" if rsi < 30 else ""
                lines.append(f"    RSI(14): {rsi:.1f} {status}")

            macd = indicators.get("macd", {})
            if isinstance(macd, dict):
                lines.append(
                    f"    MACD: {macd.get('macd', 'N/A')}, "
                    f"Signal: {macd.get('signal', 'N/A')}, "
                    f"Histogram: {macd.get('histogram', 'N/A')}"
                )

            ema = indicators.get("ema", {})
            if isinstance(ema, dict):
                lines.append(
                    f"    EMA20: {ema.get('ema_20', 'N/A')}, "
                    f"EMA50: {ema.get('ema_50', 'N/A')}"
                )

            bollinger = indicators.get("bollinger", {})
            if isinstance(bollinger, dict):
                lines.append(
                    f"    布林带: "
                    f"Upper={bollinger.get('upper', 'N/A')}, "
                    f"Middle={bollinger.get('middle', 'N/A')}, "
                    f"Lower={bollinger.get('lower', 'N/A')}"
                )

            atr = indicators.get("atr")
            if atr:
                lines.append(f"    ATR(14): {atr}")

            vol_ratio = indicators.get("volume_ratio")
            if vol_ratio:
                lines.append(f"    量比: {vol_ratio}")

            # 支撑阻力
            sr = indicators.get("support_resistance", {})
            if sr:
                supports = sr.get("support", [])[:3]
                resistances = sr.get("resistance", [])[:3]
                if supports:
                    s_strs = [
                        f"${s['level']:,.2f}" for s in supports
                    ]
                    lines.append(f"    支撑位: {', '.join(s_strs)}")
                if resistances:
                    r_strs = [
                        f"${r['level']:,.2f}" for r in resistances
                    ]
                    lines.append(f"    阻力位: {', '.join(r_strs)}")

            # K线形态
            patterns = indicators.get("patterns", {})
            if patterns:
                active = [k for k, v in patterns.items() if v]
                if active:
                    lines.append(f"    K线形态: {', '.join(active)}")

        return "\n".join(lines)

    def _format_account_data(self, data: Dict) -> str:
        """格式化账户数据"""
        return (
            f"  总余额: ${data.get('balance', 0):,.2f}\n"
            f"  可用: ${data.get('available', 0):,.2f}\n"
            f"  冻结: ${data.get('frozen', 0):,.2f}\n"
            f"  今日交易: {data.get('today_trades', 0)} 笔\n"
            f"  今日盈亏: ${data.get('today_pnl', 0):+,.2f}"
        )

    def _format_positions(self, positions: List[Dict]) -> str:
        """格式化持仓信息"""
        if not positions:
            return "  当前无持仓"

        lines = []
        for p in positions:
            lines.append(
                f"  {p['side'].upper()} {p.get('size', 0)} @ "
                f"${p.get('entry_price', 0):,.2f} "
                f"(杠杆:{p.get('leverage', 1)}x, "
                f"未实现盈亏: ${p.get('unrealized_pnl', 0):+,.2f})"
            )
            if p.get("stop_loss"):
                lines.append(f"    止损: ${p['stop_loss']:,.2f}")
            if p.get("take_profit"):
                lines.append(f"    止盈: ${p['take_profit']:,.2f}")
        return "\n".join(lines)

    def _format_memories(self, memories: List[Dict]) -> str:
        """格式化历史经验"""
        if not memories:
            return "  暂无历史交易经验 (首次运行)"

        lines = []
        for i, m in enumerate(memories[:10], 1):
            pnl = m.get("pnl_pct", 0)
            emoji = "✅" if pnl >= 0 else "❌"
            lesson = m.get("lesson", m.get("open_reason", "无"))
            lines.append(
                f"  {i}. {emoji} [{m.get('symbol', '?')}] "
                f"{m.get('side', '?')} {pnl:+.1f}% — {lesson}"
            )
        return "\n".join(lines)

    # ============================================================
    # 辅助方法
    # ============================================================
    async def _get_config(
        self, db: AsyncSession, user_id: int
    ) -> Optional[AITraderConfig]:
        """获取用户配置"""
        result = await db.execute(
            select(AITraderConfig).where(
                AITraderConfig.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def _get_next_cycle_no(
        self, db: AsyncSession, user_id: int
    ) -> int:
        """获取下一个周期编号"""
        result = await db.execute(
            select(func.max(AITraderDecision.cycle_no)).where(
                AITraderDecision.user_id == user_id,
            )
        )
        max_no = result.scalar() or 0
        return max_no + 1


# ============================================================
# 全局单例
# ============================================================
ai_trader = AITrader()
