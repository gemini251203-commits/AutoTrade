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

import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional

from loguru import logger

from app.services.alpha.base import AlphaModel, Insight
from app.services.portfolio.model import PortfolioModel, PortfolioTarget, TargetAction
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
        portfolio: Optional[PortfolioModel] = None,
        risk: Optional[RiskModel] = None,
        execution: Optional[ExecutionModel] = None,
        user_id: int = 1,
    ):
        self._alphas = alphas
        self._portfolio = portfolio
        self._risk = risk
        self._execution = execution
        self._user_id = user_id
        
        # 并发锁: 防止多个 Agent 同时提交订单时的资金校验踩踏
        self._order_lock = asyncio.Lock()
        
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
        
        async with self._order_lock:
            return await self._process_locked(
                symbol, price, db, available_balance,
                total_equity, open_positions, **kwargs,
            )
    
    async def _process_locked(
        self, symbol, price, db, available_balance,
        total_equity, open_positions, **kwargs,
    ) -> List[dict]:
        """内部方法: 在锁保护下执行四层流水线"""
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
    # 简化入口: 跳过 Alpha/Portfolio, 直走 Risk → Execution
    # ----------------------------------------------------------
    
    async def submit_order(
        self,
        db,
        symbol: str,
        side: str,               # "buy" / "sell"
        quantity: Decimal,
        leverage: int = 1,
        order_type: str = "market",
        price: Optional[Decimal] = None,
        trigger_price: Optional[Decimal] = None,
        position_side: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        source: str = "manual",
        note: str = "",
        available_balance: Decimal = Decimal("0"),
        total_equity: Decimal = Decimal("0"),
        open_positions: list = None,
    ) -> dict:
        """
        直接提交订单 (跳过 Alpha + Portfolio)
        
        适用于: 手动下单、AI Agent 下单、信号助手下单
        仍然经过 Risk Model 审批 + Execution 执行
        支持所有订单类型: market, limit, stop_market, stop_limit 等
        
        Returns:
            执行结果 dict
        """
        if open_positions is None:
            open_positions = []
        
        async with self._order_lock:
            return await self._submit_order_locked(
                db, symbol, side, quantity, leverage, order_type,
                price, trigger_price, position_side, reduce_only,
                stop_loss, take_profit, source, note,
                available_balance, total_equity, open_positions,
            )
    
    async def _submit_order_locked(
        self, db, symbol, side, quantity, leverage, order_type,
        price, trigger_price, position_side, reduce_only,
        stop_loss, take_profit, source, note,
        available_balance, total_equity, open_positions,
    ) -> dict:
        """内部方法: 在锁保护下执行 Risk → Execution"""
        
        # 构建 PortfolioTarget
        action = TargetAction.OPEN_LONG if side.lower() == "buy" else TargetAction.OPEN_SHORT
        
        current_price = price or Decimal("0")
        notional = quantity * current_price if current_price else Decimal("0")
        required_margin = notional / Decimal(str(leverage)) if leverage > 0 else notional
        
        target = PortfolioTarget(
            symbol=symbol,
            action=action,
            quantity=quantity,
            leverage=leverage,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            position_side=position_side,
            reduce_only=reduce_only,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            notional=notional,
            required_margin=required_margin,
            source=source,
        )

        
        logger.info(f"[Pipeline] submit_order: {target.summary()} source={source}")
        
        # Risk 审批
        verdict = await self._risk.approve_target(
            target=target,
            available_balance=available_balance,
            total_equity=total_equity,
            open_positions=open_positions,
            user_id=self._user_id,
        )
        
        if not verdict.approved:
            self._stats["risk_rejected"] += 1
            logger.warning(f"[Pipeline] ❌ Risk rejected submit_order: {verdict.reason}")
            
            # ★ 写入拦截日志 ("死海古卷")
            try:
                import re
                from app.models.intercepted_order import InterceptedOrder
                
                # 从 note 解析 agent_name
                intercept_agent_name = None
                if note:
                    agent_match = re.match(r'\[(\w+):([^\]]+)\]', note)
                    if agent_match:
                        intercept_agent_name = agent_match.group(2).strip()
                
                intercepted = InterceptedOrder(
                    user_id=self._user_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    leverage=leverage,
                    price_at_intercept=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    intercept_reason=verdict.reason,
                    intercept_source="pipeline_risk",
                    source=source or "unknown",
                    agent_name=intercept_agent_name,
                )
                db.add(intercepted)
                # 不 commit, 让调用方决定事务
                logger.info(
                    f"[Pipeline] 📜 Intercepted order logged: {symbol} {side} "
                    f"agent={intercept_agent_name} reason={verdict.reason[:50]}"
                )
            except Exception as e:
                logger.warning(f"[Pipeline] Failed to log intercepted order: {e}")
            
            return {
                "success": False,
                "error": f"风控拒绝: {verdict.reason}",
                "risk_reason": verdict.reason,
                "symbol": symbol,
            }
        
        self._stats["risk_approved"] += 1
        final_target = verdict.adjusted_target or target
        
        # 如果 note 非空，附加到 target metadata
        if note:
            final_target.metadata["note"] = note
        
        # Execution
        exec_result = await self._execution.execute(
            target=final_target,
            db=db,
            user_id=self._user_id,
        )
        
        if exec_result.get("success"):
            self._stats["orders_executed"] += 1
        else:
            self._stats["errors"] += 1
        
        return exec_result
    
    async def submit_from_signal(
        self,
        db,
        symbol: str,
        side: str,               # "buy" / "sell" 
        quantity: Decimal,
        leverage: int,
        price: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        source: str = "quant",
        strategy_name: str = "",
        available_balance: Decimal = Decimal("0"),
        total_equity: Decimal = Decimal("0"),
        open_positions: list = None,
    ) -> dict:
        """
        从策略信号提交订单 (跳过 Alpha, 可选 Portfolio)
        
        适用于: 量化策略评估结果 → 直接下单
        仍然经过 Risk Model 审批 + Execution 执行
        
        Returns:
            执行结果 dict
        """
        result = await self.submit_order(
            db=db,
            symbol=symbol,
            side=side,
            quantity=quantity,
            leverage=leverage,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=source,
            note=f"Strategy: {strategy_name}" if strategy_name else "",
            available_balance=available_balance,
            total_equity=total_equity,
            open_positions=open_positions,
        )
        return result
    
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


# ============================================================
# 全局单例: 供所有调用者共享
# ============================================================

_global_pipeline: Optional[TradingPipeline] = None


def get_pipeline(user_id: int = 1) -> TradingPipeline:
    """
    获取全局 Pipeline 实例
    
    所有交易来源 (手动/AI/策略/网格) 都应通过这个实例提交订单,
    确保所有交易统一经过 Risk → Execution 流程。
    
    自动注册 ExternalSignalAlpha 适配器:
    - news_monitor: 新闻监控的交易信号
    """
    global _global_pipeline
    
    if _global_pipeline is None or _global_pipeline._user_id != user_id:
        from app.services.alpha.external_signal import ExternalSignalAlpha
        
        _global_pipeline = TradingPipeline(
            alphas=[
                ExternalSignalAlpha(name="news_monitor"),
            ],
            portfolio=None,             # submit_order 不需要 Portfolio
            risk=RiskModel(),
            execution=ExecutionModel(),
            user_id=user_id,
        )
        logger.info(f"[Pipeline] Global pipeline created for user_id={user_id} with signal adapters")
    
    return _global_pipeline

