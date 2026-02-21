"""
Trading Pipeline — LEAN 四层流水线编排器
=========================================
核心编排: Alpha → Portfolio → Risk → Execution

这是整个架构的大脑 — 协调四个模型层的工作:

    TICK (via EventBus)
         │
         ▼
    ┌─────────────┐
    │  Alpha Model │  信号产出 (Insight)
    └──────┬──────┘
           │ List[Insight]
           ▼
    ┌─────────────────┐
    │  Portfolio Model │  仓位计算 (Target)
    └──────┬──────────┘
           │ PortfolioTarget
           ▼
    ┌─────────────┐
    │  Risk Model  │  审批/否决
    └──────┬──────┘
           │ RiskVerdict
           ▼
    ┌──────────────────┐
    │  Execution Model │  下单执行
    └──────────────────┘

使用方式:
    pipeline = TradingPipeline(
        alphas=[YamlAlpha(config), AgentAlpha(user_id=1)],
        portfolio=FixedPercentModel(),
        risk=RiskModel(),
        execution=ExecutionModel(),
    )
    
    # 手动触发一次
    results = await pipeline.process(symbol="ETHUSDT", price=3200, ...)
    
    # 或者自动从 EventBus 接收 TICK
    pipeline.start_listening()
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.alpha.base import AlphaModel, Insight
from app.services.portfolio.model import PortfolioModel, PortfolioTarget
from app.services.risk.risk_model import RiskModel, RiskVerdict
from app.services.execution.model import ExecutionModel
from app.core.event_bus import event_bus, Event, EventType


class TradingPipeline:
    """
    四层流水线编排器
    
    将 Alpha、Portfolio、Risk、Execution 串联:
    1. TICK → Alpha.update() → List[Insight]
    2. Insight → Portfolio.calculate_target() → PortfolioTarget
    3. Target → Risk.approve_target() → RiskVerdict
    4. Approved → Execution.execute() → Order
    """
    
    def __init__(
        self,
        alphas: List[AlphaModel],
        portfolio: PortfolioModel,
        risk: RiskModel,
        execution: ExecutionModel,
        user_id: int = 1,
    ):
        self._alphas = alphas
        self._portfolio = portfolio
        self._risk = risk
        self._execution = execution
        self._user_id = user_id
        
        # 统计
        self._stats = {
            "ticks_processed": 0,
            "insights_generated": 0,
            "targets_created": 0,
            "risk_approved": 0,
            "risk_rejected": 0,
            "orders_executed": 0,
            "errors": 0,
        }
    
    # ----------------------------------------------------------
    # 核心方法: 处理一个 price tick
    # ----------------------------------------------------------
    
    async def process(
        self,
        symbol: str,
        price: Decimal,
        db=None,
        available_balance: Decimal = Decimal("0"),
        total_equity: Decimal = Decimal("0"),
        open_positions: list = None,
        **kwargs,
    ) -> List[dict]:
        """
        处理一次价格更新, 完整走过四层流水线
        
        Returns:
            执行结果列表
        """
        if open_positions is None:
            open_positions = []
        
        results = []
        self._stats["ticks_processed"] += 1
        
        # ===== Layer 1: Alpha =====
        all_insights: List[Insight] = []
        
        for alpha in self._alphas:
            try:
                insights = await alpha.safe_update(
                    symbol=symbol,
                    price=price,
                    **kwargs,
                )
                all_insights.extend(insights)
            except Exception as e:
                logger.error(f"[Pipeline] Alpha {alpha.get_name()} error: {e}")
                self._stats["errors"] += 1
        
        if not all_insights:
            return results
        
        self._stats["insights_generated"] += len(all_insights)
        
        # 发布 INSIGHT 事件 (供监控/记录)
        for insight in all_insights:
            await event_bus.emit(Event(
                type=EventType.INSIGHT,
                data={
                    "symbol": insight.symbol,
                    "direction": insight.direction.value,
                    "confidence": insight.confidence,
                    "source": insight.source,
                },
                source="pipeline",
                user_id=self._user_id,
            ))
        
        # ===== Layer 2: Portfolio =====
        for insight in all_insights:
            if not insight.is_actionable:
                continue
            
            try:
                target = await self._portfolio.calculate_target(
                    insight=insight,
                    current_price=price,
                    available_balance=available_balance,
                    existing_positions=open_positions,
                )
                
                if target is None:
                    continue
                
                self._stats["targets_created"] += 1
                
                # ===== Layer 3: Risk =====
                verdict = await self._risk.approve_target(
                    target=target,
                    available_balance=available_balance,
                    total_equity=total_equity,
                    open_positions=open_positions,
                    user_id=self._user_id,
                )
                
                if not verdict.approved:
                    self._stats["risk_rejected"] += 1
                    logger.warning(
                        f"[Pipeline] ❌ Risk rejected: {verdict.reason}"
                    )
                    
                    # 发布 RISK_VETO 事件
                    await event_bus.emit(Event(
                        type=EventType.RISK_VETO,
                        data={
                            "symbol": target.symbol,
                            "reason": verdict.reason,
                            "target": target.summary(),
                        },
                        source="pipeline",
                        user_id=self._user_id,
                    ))
                    continue
                
                self._stats["risk_approved"] += 1
                
                # 使用调整后的 target (如果有)
                final_target = verdict.adjusted_target or target
                
                # ===== Layer 4: Execution =====
                if db is None:
                    logger.warning("[Pipeline] No db session, skip execution")
                    results.append({
                        "success": False,
                        "reason": "no db session",
                        "target": final_target.summary(),
                    })
                    continue
                
                exec_result = await self._execution.execute(
                    target=final_target,
                    db=db,
                    user_id=self._user_id,
                )
                
                if exec_result.get("success"):
                    self._stats["orders_executed"] += 1
                else:
                    self._stats["errors"] += 1
                
                results.append(exec_result)
                
            except Exception as e:
                logger.error(f"[Pipeline] Error processing insight: {e}")
                self._stats["errors"] += 1
        
        return results
    
    # ----------------------------------------------------------
    # EventBus 集成
    # ----------------------------------------------------------
    
    def start_listening(self) -> None:
        """注册为 TICK 事件订阅者"""
        event_bus.subscribe(
            EventType.TICK,
            self._on_tick,
            priority=5,                 # 低于风控(100)和订单检查(10)
            name="trading_pipeline",
        )
        logger.info(
            f"[Pipeline] Listening for TICK events with "
            f"{len(self._alphas)} alphas"
        )
    
    async def _on_tick(self, event: Event) -> None:
        """处理 TICK 事件"""
        symbol = event.data.get("symbol")
        price = event.data.get("price")
        
        if not symbol or not price:
            return
        
        # 获取账户信息 — 需要 db session
        from app.db.session import AsyncSessionLocal
        
        try:
            async with AsyncSessionLocal() as db:
                # 获取钱包信息
                from sqlalchemy import select
                from app.models.wallet import Wallet
                from app.models.position import Position, PositionStatus
                
                wallet_result = await db.execute(
                    select(Wallet).where(Wallet.user_id == self._user_id)
                )
                wallet = wallet_result.scalar_one_or_none()
                
                available_balance = Decimal(str(wallet.balance)) if wallet else Decimal("0")
                total_equity = Decimal(str(wallet.total_equity)) if wallet else Decimal("0")
                
                # 获取持仓
                pos_result = await db.execute(
                    select(Position).where(
                        Position.user_id == self._user_id,
                        Position.status == PositionStatus.OPEN,
                    )
                )
                positions = pos_result.scalars().all()
                open_positions = [
                    {
                        "symbol": p.symbol,
                        "side": p.side.value,
                        "size": float(p.size),
                        "notional": float(p.size * price),  # 近似
                    }
                    for p in positions
                ]
                
                await self.process(
                    symbol=symbol,
                    price=price,
                    db=db,
                    available_balance=available_balance,
                    total_equity=total_equity,
                    open_positions=open_positions,
                )
                
                await db.commit()
                
        except Exception as e:
            logger.error(f"[Pipeline] TICK handler error: {e}")
    
    # ----------------------------------------------------------
    # 管理
    # ----------------------------------------------------------
    
    def get_stats(self) -> dict:
        """获取流水线统计"""
        return {
            **self._stats,
            "alphas": [a.get_stats() for a in self._alphas],
        }
    
    def add_alpha(self, alpha: AlphaModel) -> None:
        """动态添加 Alpha 模型"""
        self._alphas.append(alpha)
        logger.info(
            f"[Pipeline] Added alpha: {alpha.get_name()} "
            f"(total: {len(self._alphas)})"
        )
    
    def remove_alpha(self, name: str) -> bool:
        """按名称移除 Alpha"""
        for i, alpha in enumerate(self._alphas):
            if alpha.get_name() == name:
                self._alphas.pop(i)
                logger.info(f"[Pipeline] Removed alpha: {name}")
                return True
        return False
