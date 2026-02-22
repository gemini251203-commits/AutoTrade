"""
StrategyScheduler - 策略自动调度器 (原 AutoPilot)
=================================================
量化策略自动执行管道:

    调度器 → 指标计算 → 策略评估 → AI 审核 → 风控检查 → 自动下单 → AI 反思

注意: 与 agent/autopilot.py (AI 对话决策) 不同:
- 本模块: 基于 YAML 策略条件自动执行, 无需 AI 对话
- agent/autopilot: 基于 AI Agent 自由分析决策

运行方式:
    1. 作为独立容器: python -m app.services.quant.strategy_scheduler
    2. 或集成到 FastAPI 后台任务中
"""

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.strategy import Strategy, StrategyLog, TradeMemory
from app.models.order import OrderSide, OrderType, PositionSideEnum
from app.services.quant.indicators import calculate_all_indicators
from app.services.quant.strategy import StrategyEngine, Signal, SignalType
from app.services.risk.risk_model import RiskModel
from app.services.quant.ai_reviewer import AIReviewer
from app.services.quant.reflector import TradeReflector
from app.core.constants import INTERVAL_SECONDS


class AutoPilot:
    """
    AI 自动交易驾驶
    
    每个策略按其 interval 周期运行一次评估周期
    """

    def __init__(self):
        self.strategy_engine = StrategyEngine()
        self.risk_guard = RiskModel()
        self.ai_reviewer: Optional[AIReviewer] = None
        self.reflector: Optional[TradeReflector] = None
        self._running = False
        self._tasks: Dict[int, asyncio.Task] = {}

    def _init_ai_services(self):
        """懒加载 AI 服务（需要配置文件）"""
        if self.ai_reviewer is not None:
            return
        try:
            from app.core.config import settings
            from app.services.ai.providers import DeepSeekProvider
            
            provider = DeepSeekProvider(
                api_key=settings.deepseek_api_key,
                model=getattr(settings, "deepseek_model", "deepseek-chat"),
            )
            self.ai_reviewer = AIReviewer(provider)
            self.reflector = TradeReflector(provider)
            logger.info("[AutoPilot] AI 服务初始化成功")
        except Exception as e:
            logger.warning(f"[AutoPilot] AI 服务初始化失败: {e}，将跳过 AI 审核")

    async def start(self):
        """启动自动交易调度"""
        self._running = True
        self._init_ai_services()
        logger.info("[AutoPilot] 🚀 自动交易调度器启动")
        
        while self._running:
            try:
                await self._scan_and_dispatch()
            except Exception as e:
                logger.error(f"[AutoPilot] 调度器异常: {e}")
            
            # 每 30 秒检查一次有没有新策略要启动/停止
            await asyncio.sleep(30)

    async def stop(self):
        """停止调度"""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        logger.info("[AutoPilot] 🛑 自动交易调度器已停止")

    async def _scan_and_dispatch(self):
        """扫描所有活跃策略，为每个创建/管理独立的运行任务"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Strategy).where(Strategy.is_active == True)
            )
            active_strategies = result.scalars().all()
        
        active_ids = {s.id for s in active_strategies}
        
        # 停止已经不活跃的任务
        for sid in list(self._tasks.keys()):
            if sid not in active_ids:
                self._tasks[sid].cancel()
                del self._tasks[sid]
                logger.info(f"[AutoPilot] 策略 #{sid} 已停止")
        
        # 启动新的活跃策略
        for strat in active_strategies:
            if strat.id not in self._tasks:
                task = asyncio.create_task(
                    self._run_strategy_loop(strat.id, strat.interval)
                )
                self._tasks[strat.id] = task
                logger.info(
                    f"[AutoPilot] 策略 #{strat.id} '{strat.name}' 已启动 "
                    f"({strat.symbol} {strat.interval})"
                )

    async def _run_strategy_loop(self, strategy_id: int, interval: str):
        """单个策略的运行循环"""
        sleep_seconds = INTERVAL_SECONDS.get(interval, 3600)
        
        while True:
            try:
                await self.run_cycle(strategy_id)
            except asyncio.CancelledError:
                logger.info(f"[AutoPilot] 策略 #{strategy_id} 循环取消")
                return
            except Exception as e:
                logger.error(f"[AutoPilot] 策略 #{strategy_id} 执行异常: {e}")
            
            await asyncio.sleep(sleep_seconds)

    async def run_cycle(self, strategy_id: int):
        """
        一个完整的策略评估+执行周期
        
        1. 读取策略 YAML 配置
        2. 获取最新 K 线和指标
        3. 策略引擎评估 → 候选信号
        4. AI 审核员: 结合市场环境+记忆做增强判断
        5. 风控守卫检查
        6. 通过 → 自动下单
        7. 交易结果 → AI 反思 → 写入记忆
        """
        async with AsyncSessionLocal() as db:
            # 1. 读取策略
            result = await db.execute(
                select(Strategy).where(Strategy.id == strategy_id)
            )
            strategy = result.scalar_one_or_none()
            if not strategy or not strategy.is_active:
                return

            logger.info(
                f"[AutoPilot] ▶ 策略 #{strategy.id} '{strategy.name}' "
                f"({strategy.symbol}) 开始评估"
            )

            # 2. 获取 K 线数据
            klines = await self._fetch_klines(strategy.symbol, strategy.interval)
            if not klines or len(klines) < 50:
                logger.warning(f"[AutoPilot] K 线数据不足: {len(klines) if klines else 0}")
                await self._save_log(
                    db, strategy, "none", "no_data",
                    ai_reason="K 线数据不足，跳过评估"
                )
                return

            # 3. 策略评估
            try:
                config = self.strategy_engine.parse_yaml(strategy.config_yaml)
                signal = self.strategy_engine.evaluate(config, klines)
            except Exception as e:
                logger.error(f"[AutoPilot] 策略评估异常: {e}")
                await self._save_log(
                    db, strategy, "none", "error",
                    ai_reason=f"策略评估异常: {str(e)}"
                )
                return

            # 更新上次运行时间
            strategy.last_run_at = datetime.utcnow()
            strategy.last_signal = signal.signal_type.value

            # 无信号 → 跳过
            if not signal.has_signal:
                await self._save_log(
                    db, strategy, "none", "no_signal",
                    conditions_snapshot=self._snapshot_conditions(signal)
                )
                await db.commit()
                return

            logger.info(f"[AutoPilot] 📡 候选信号: {signal.summary()}")

            # 4. AI 审核
            ai_approve = True
            ai_confidence = 1.0
            ai_reason = "AI 审核已跳过"
            
            if self.ai_reviewer and signal.ai_prompt:
                memories = await self._load_memories(
                    db, strategy.user_id, strategy.symbol
                )
                review = await self.ai_reviewer.review(signal, klines, memories)
                ai_approve = review.approve
                ai_confidence = review.confidence
                ai_reason = review.reason
                
                if not ai_approve:
                    logger.info(f"[AutoPilot] ❌ AI 拒绝: {ai_reason}")
                    await self._save_log(
                        db, strategy, signal.signal_type.value, "rejected_ai",
                        side=signal.side.value if signal.side else None,
                        ai_approve=False,
                        ai_confidence=ai_confidence,
                        ai_reason=ai_reason,
                        conditions_snapshot=self._snapshot_conditions(signal),
                    )
                    await db.commit()
                    return

            # 5. 风控参数钳制 (确保参数在系统限制内)
            risk_config = signal.risk_config
            risk_config = self.risk_guard.clamp_params(risk_config)
            
            wallet_balance = await self._get_wallet_balance(db, strategy.user_id)

            # 6. 通过 Pipeline 统一下单 (Pipeline 内部含 Risk 审批)
            logger.info(f"[AutoPilot] 信号确认，通过 Pipeline 下单")
            exec_result = await self._execute_order(
                db, strategy, signal, risk_config, wallet_balance
            )
            
            order_id = exec_result.get("order_id") if exec_result else None
            risk_passed = exec_result.get("risk_passed", True) if exec_result else False
            risk_reason = exec_result.get("risk_reason", "") if exec_result else "执行失败"
            
            if not exec_result or not exec_result.get("success"):
                # Pipeline 拒绝 (可能是风控拒绝或执行失败)
                action = "rejected_risk" if not risk_passed else "error"
                logger.info(f"[AutoPilot] Pipeline 拒绝: {risk_reason}")
                await self._save_log(
                    db, strategy, signal.signal_type.value, action,
                    side=signal.side.value if signal.side else None,
                    ai_approve=ai_approve,
                    ai_confidence=ai_confidence,
                    ai_reason=ai_reason,
                    risk_passed=risk_passed,
                    risk_reason=risk_reason,
                    conditions_snapshot=self._snapshot_conditions(signal),
                )
                await db.commit()
                return
            
            # 7. 记录成功日志
            strategy.total_trades += 1
            await self._save_log(
                db, strategy, signal.signal_type.value, "executed",
                side=signal.side.value if signal.side else None,
                ai_approve=ai_approve,
                ai_confidence=ai_confidence,
                ai_reason=ai_reason,
                risk_passed=True,
                order_id=order_id,
                conditions_snapshot=self._snapshot_conditions(signal),
            )
            
            await db.commit()
            logger.info(
                f"[AutoPilot] 策略 #{strategy.id} 交易已执行 "
                f"(order_id={order_id})"
            )

    # ============================================================
    # 辅助方法
    # ============================================================

    async def _fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 200,
    ) -> List[Dict]:
        """从交易所获取 K 线数据"""
        try:
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            raw_klines = await client.get_klines(symbol, interval, limit=limit)
            
            if not raw_klines:
                return []
            
            # 转换为标准格式
            result = []
            for k in raw_klines:
                result.append({
                    "open_time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })
            return result
        except Exception as e:
            logger.error(f"[AutoPilot] 获取 K 线失败: {e}")
            return []

    async def _load_memories(
        self,
        db: AsyncSession,
        user_id: int,
        symbol: str,
        limit: int = 5,
    ) -> List[Dict]:
        """加载交易记忆"""
        result = await db.execute(
            select(TradeMemory)
            .where(
                TradeMemory.user_id == user_id,
                TradeMemory.symbol == symbol,
            )
            .order_by(TradeMemory.created_at.desc())
            .limit(limit)
        )
        memories = result.scalars().all()
        return [
            {
                "symbol": m.symbol,
                "trade_result": m.trade_result,
                "lesson": m.lesson,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in memories
        ]

    async def _get_wallet_balance(self, db: AsyncSession, user_id: int) -> float:
        """获取用户钱包余额"""
        try:
            from app.services.wallet import WalletManager
            wallet = await WalletManager.get_or_create_wallet(db, user_id)
            return float(wallet.balance)
        except Exception as e:
            logger.warning(f"[AutoPilot] 获取钱包余额失败: {e}")
            return 0.0

    async def _get_open_positions(
        self, db: AsyncSession, user_id: int
    ) -> List[Dict]:
        """获取当前持仓"""
        try:
            from app.models.position import Position, PositionStatus
            result = await db.execute(
                select(Position).where(
                    Position.user_id == user_id,
                    Position.status == PositionStatus.OPEN,
                )
            )
            positions = result.scalars().all()
            return [
                {
                    "symbol": p.symbol,
                    "notional": float(p.notional_value) if hasattr(p, 'notional_value') else 0,
                    "side": p.side.value if hasattr(p, 'side') else "long",
                }
                for p in positions
            ]
        except Exception as e:
            logger.warning(f"[AutoPilot] 获取持仓失败: {e}")
            return []

    async def _get_today_stats(
        self, db: AsyncSession, user_id: int
    ) -> tuple:
        """获取今日交易统计"""
        try:
            today_start = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            result = await db.execute(
                select(StrategyLog)
                .where(
                    StrategyLog.user_id == user_id,
                    StrategyLog.action == "executed",
                    StrategyLog.created_at >= today_start,
                )
            )
            logs = result.scalars().all()
            today_trades = len(logs)
            today_pnl = sum(log.pnl or 0 for log in logs)
            return today_trades, today_pnl
        except Exception:
            return 0, 0.0

    async def _execute_order(
        self,
        db: AsyncSession,
        strategy: Strategy,
        signal: Signal,
        risk_config: Dict,
        wallet_balance: float,
    ) -> Dict:
        """执行下单 (通过 Pipeline 统一入口, 含 Risk 审批)
        
        Returns:
            dict with keys: success, order_id, risk_passed, risk_reason, error
        """
        try:
            from app.core.pipeline import get_pipeline
            
            side_str = signal.side.value if signal.side else "buy"
            leverage = risk_config.get("leverage", 1)
            position_pct = risk_config.get("position_pct", 10)
            
            # 计算下单金额和数量
            trade_amount = wallet_balance * position_pct / 100
            
            # 获取当前价格
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            ticker = await client.get_ticker(strategy.symbol)
            current_price = float(ticker.get("lastPrice", 0)) if ticker else 0
            
            if current_price <= 0:
                logger.error(f"[AutoPilot] 无法获取 {strategy.symbol} 价格")
                return {"success": False, "risk_passed": True, "risk_reason": "", "error": "无法获取价格"}
            
            quantity = Decimal(str(trade_amount * leverage / current_price))
            
            # 计算止损止盈价格
            stop_loss_pct = risk_config.get("stop_loss_pct", 3)
            take_profit_pct = risk_config.get("take_profit_pct", 9)
            
            if side_str == "buy":
                stop_loss = Decimal(str(current_price * (1 - stop_loss_pct / 100)))
                take_profit = Decimal(str(current_price * (1 + take_profit_pct / 100)))
            else:
                stop_loss = Decimal(str(current_price * (1 + stop_loss_pct / 100)))
                take_profit = Decimal(str(current_price * (1 - take_profit_pct / 100)))
            
            # 获取持仓信息
            open_positions = await self._get_open_positions(db, strategy.user_id)
            
            # 通过 Pipeline 下单 (内含 Risk 审批)
            pipeline = get_pipeline(strategy.user_id)
            result = await pipeline.submit_from_signal(
                db=db,
                symbol=strategy.symbol,
                side=side_str,
                quantity=quantity,
                leverage=leverage,
                price=Decimal(str(current_price)),
                stop_loss=stop_loss,
                take_profit=take_profit,
                source="autopilot",
                strategy_name=strategy.name,
                available_balance=Decimal(str(wallet_balance)),
                total_equity=Decimal(str(wallet_balance)),
                open_positions=open_positions,
            )
            
            if result.get("success"):
                return {
                    "success": True,
                    "order_id": result.get("order_id"),
                    "risk_passed": True,
                    "risk_reason": "",
                }
            else:
                # 判断是风控拒绝还是执行失败
                error_msg = result.get("error", "")
                is_risk_reject = "风控拒绝" in error_msg or "risk_reason" in result
                return {
                    "success": False,
                    "order_id": None,
                    "risk_passed": not is_risk_reject,
                    "risk_reason": result.get("risk_reason", error_msg),
                    "error": error_msg,
                }
        except Exception as e:
            logger.error(f"[AutoPilot] 下单失败: {e}")
            return {"success": False, "risk_passed": True, "risk_reason": "", "error": str(e)}


    async def _save_log(
        self,
        db: AsyncSession,
        strategy: Strategy,
        signal_type: str,
        action: str,
        side: Optional[str] = None,
        ai_approve: Optional[bool] = None,
        ai_confidence: Optional[float] = None,
        ai_reason: Optional[str] = None,
        risk_passed: Optional[bool] = None,
        risk_reason: Optional[str] = None,
        order_id: Optional[int] = None,
        pnl: Optional[float] = None,
        conditions_snapshot: Optional[str] = None,
    ):
        """保存执行日志"""
        log = StrategyLog(
            strategy_id=strategy.id,
            user_id=strategy.user_id,
            signal_type=signal_type,
            action=action,
            side=side,
            ai_approve=ai_approve,
            ai_confidence=ai_confidence,
            ai_reason=ai_reason,
            risk_passed=risk_passed,
            risk_reason=risk_reason,
            order_id=order_id,
            pnl=pnl,
            conditions_snapshot=conditions_snapshot,
        )
        db.add(log)

    def _snapshot_conditions(self, signal: Signal) -> str:
        """条件评估快照 (JSON)"""
        try:
            data = {
                "met": [str(c) for c in signal.conditions_met],
                "failed": [str(c) for c in signal.conditions_failed],
            }
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return "{}"


# ============================================================
# 独立运行入口
# ============================================================

async def main():
    """作为独立进程运行"""
    logger.info("=" * 60)
    logger.info("AutoPilot - AI 自动交易调度器")
    logger.info("=" * 60)
    
    pilot = AutoPilot()
    try:
        await pilot.start()
    except KeyboardInterrupt:
        await pilot.stop()


if __name__ == "__main__":
    asyncio.run(main())
