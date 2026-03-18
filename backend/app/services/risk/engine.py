"""
Risk Engine Service
====================
风控引擎 - 监控仓位风险并执行强制平仓

核心功能:
1. 计算仓位的未实现盈亏 (Unrealized PnL)
2. 计算保证金率 (Margin Ratio)
3. 监控强平价格触发
4. 执行强制平仓

关键公式:
- 未实现盈亏 (多头) = (标记价 - 开仓价) × 数量
- 未实现盈亏 (空头) = (开仓价 - 标记价) × 数量
- 保证金率 = (保证金 + 未实现盈亏) / 名义价值
- 维持保证金率 = 0.4% (Binance 默认)

强平触发条件:
- 保证金率 < 维持保证金率
- 或标记价触及强平价
"""

from decimal import Decimal
from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.position import Position, PositionSide, PositionStatus
from app.services.trading import PositionManager


# 默认风控参数
DEFAULT_MAINTENANCE_MARGIN_RATE = Decimal("0.004")  # 0.4% 维持保证金率
DEFAULT_LIQUIDATION_FEE_RATE = Decimal("0.0015")    # 0.15% 强平手续费


@dataclass
class PositionRisk:
    """仓位风险数据"""
    position_id: int
    symbol: str
    side: PositionSide
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    leverage: int
    margin: Decimal
    margin_mode: str  # 'cross' or 'isolated'
    liquidation_price: Decimal
    unrealized_pnl: Decimal
    roe_percent: Decimal
    margin_ratio: Decimal
    is_at_risk: bool
    should_liquidate: bool
    # 🔥 新增止盈止损字段
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    source: str = "manual"


@dataclass
class AccountRisk:
    """账户风险汇总"""
    user_id: int
    total_margin: Decimal
    total_unrealized_pnl: Decimal
    total_equity: Decimal
    margin_ratio: Decimal
    positions_at_risk: int
    positions_to_liquidate: int


class RiskEngine:
    """
    风控引擎
    
    核心方法:
    - calculate_position_risk: 计算单个仓位的风险
    - calculate_account_risk: 计算账户整体风险
    - check_liquidation: 检查是否需要强平
    - execute_liquidation: 执行强制平仓
    - monitor_positions: 批量监控仓位 (定时任务调用)
    """
    
    @staticmethod
    def calculate_unrealized_pnl(
        side: PositionSide,
        size: Decimal,
        entry_price: Decimal,
        mark_price: Decimal,
    ) -> Decimal:
        """
        计算未实现盈亏 (兼容旧调用)
        
        NOTE: 推荐直接使用 position.calculate_unrealized_pnl(mark_price)
        """
        if side == PositionSide.LONG:
            return (mark_price - entry_price) * size
        else:
            return (entry_price - mark_price) * size
    
    @staticmethod
    def calculate_roe(
        unrealized_pnl: Decimal,
        margin: Decimal,
    ) -> Decimal:
        """
        计算收益率 (ROE)
        
        ROE = 未实现盈亏 / 保证金 × 100%
        """
        if margin == 0:
            return Decimal("0")
        return (unrealized_pnl / margin) * 100
    
    @staticmethod
    def calculate_margin_ratio(
        margin: Decimal,
        unrealized_pnl: Decimal,
        notional_value: Decimal,
    ) -> Decimal:
        """
        计算保证金率
        
        保证金率 = (保证金 + 未实现盈亏) / 名义价值
        
        名义价值 = 数量 × 标记价
        """
        if notional_value == 0:
            return Decimal("999")  # 无仓位返回高保证金率
        effective_margin = margin + unrealized_pnl
        return effective_margin / notional_value
    
    @staticmethod
    def calculate_position_risk(
        position: Position,
        mark_price: Decimal,
        maintenance_margin_rate: Decimal = DEFAULT_MAINTENANCE_MARGIN_RATE,
    ) -> PositionRisk:
        """
        计算单个仓位的风险
        
        Args:
            position: 仓位对象
            mark_price: 当前标记价格
            maintenance_margin_rate: 维持保证金率
            
        Returns:
            PositionRisk 数据对象
        """
        # 计算未实现盈亏 — 使用 Position 模型的方法 (唯一权威实现)
        unrealized_pnl = position.calculate_unrealized_pnl(mark_price)
        
        # 计算 ROE
        roe = RiskEngine.calculate_roe(unrealized_pnl, position.margin)
        
        # 计算名义价值和保证金率
        notional_value = position.size * mark_price
        margin_ratio = RiskEngine.calculate_margin_ratio(
            position.margin,
            unrealized_pnl,
            notional_value,
        )
        
        # 判断是否触发强平
        is_at_risk = margin_ratio < maintenance_margin_rate * 2  # 接近强平线
        
        # 检查是否应该强平
        should_liquidate = False
        if position.liquidation_price:
            if position.side == PositionSide.LONG:
                should_liquidate = mark_price <= position.liquidation_price
            else:
                should_liquidate = mark_price >= position.liquidation_price
        
        # 如果保证金率低于维持保证金率也应该强平
        if margin_ratio < maintenance_margin_rate:
            should_liquidate = True
        
        return PositionRisk(
            position_id=position.id,
            symbol=position.symbol,
            side=position.side,
            size=position.size,
            entry_price=position.entry_price,
            mark_price=mark_price,
            leverage=position.leverage,
            margin=position.margin,
            margin_mode=position.margin_mode.value if hasattr(position.margin_mode, 'value') else str(position.margin_mode),
            liquidation_price=position.liquidation_price,
            unrealized_pnl=unrealized_pnl,
            roe_percent=roe,
            margin_ratio=margin_ratio,
            is_at_risk=is_at_risk,
            should_liquidate=should_liquidate,
            # 🔥 填充止盈止损
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            source=getattr(position, 'source', 'manual') or 'manual',
        )
    
    @staticmethod
    async def calculate_account_risk(
        db: AsyncSession,
        user_id: int,
        price_map: Dict[str, Decimal],
    ) -> AccountRisk:
        """
        计算账户整体风险
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            price_map: 交易对 → 标记价格映射
            
        Returns:
            AccountRisk 账户风险汇总
        """
        # 获取用户所有开放仓位
        positions = await PositionManager.get_user_positions(
            db, user_id, PositionStatus.OPEN
        )
        
        total_margin = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        positions_at_risk = 0
        positions_to_liquidate = 0
        
        for position in positions:
            mark_price = price_map.get(position.symbol, position.entry_price)
            
            risk = RiskEngine.calculate_position_risk(position, mark_price)
            
            total_margin += position.margin
            total_unrealized_pnl += risk.unrealized_pnl
            
            if risk.is_at_risk:
                positions_at_risk += 1
            if risk.should_liquidate:
                positions_to_liquidate += 1
        
        total_equity = total_margin + total_unrealized_pnl
        
        # 账户保证金率 (简化: 使用总权益/总保证金)
        account_margin_ratio = (
            total_equity / total_margin if total_margin > 0 else Decimal("999")
        )
        
        return AccountRisk(
            user_id=user_id,
            total_margin=total_margin,
            total_unrealized_pnl=total_unrealized_pnl,
            total_equity=total_equity,
            margin_ratio=account_margin_ratio,
            positions_at_risk=positions_at_risk,
            positions_to_liquidate=positions_to_liquidate,
        )
    
    @staticmethod
    async def execute_liquidation(
        db: AsyncSession,
        position_id: int,
    ) -> Position:
        """
        执行强制平仓
        
        以强平价格平掉全部仓位
        """
        logger.warning(f"[RiskEngine] Executing liquidation: position_id={position_id}")
        
        position = await PositionManager.liquidate_position(db, position_id)
        
        logger.warning(
            f"[RiskEngine] Liquidation complete: "
            f"symbol={position.symbol}, side={position.side.value}, "
            f"pnl={position.realized_pnl}"
        )
        
        return position
    
    @staticmethod
    async def monitor_positions(
        db: AsyncSession,
        price_map: Dict[str, Decimal],
    ) -> List[Position]:
        """
        批量监控所有开放仓位
        
        检查所有仓位是否触发强平条件，
        对需要强平的仓位执行强制平仓。
        
        Args:
            db: 数据库会话
            price_map: 交易对 → 标记价格映射
            
        Returns:
            已强平的仓位列表
        """
        # 获取所有开放仓位
        result = await db.execute(
            select(Position).where(Position.status == PositionStatus.OPEN)
        )
        all_positions = result.scalars().all()
        
        liquidated_positions = []
        
        for position in all_positions:
            mark_price = price_map.get(position.symbol)
            
            if not mark_price:
                continue
            
            risk = RiskEngine.calculate_position_risk(position, mark_price)
            
            if risk.should_liquidate:
                logger.warning(
                    f"[RiskEngine] Position needs liquidation: "
                    f"id={position.id}, symbol={position.symbol}, "
                    f"side={position.side.value}, mark_price={mark_price}, "
                    f"liq_price={position.liquidation_price}, "
                    f"margin_ratio={risk.margin_ratio:.4f}"
                )
                
                try:
                    liquidated = await RiskEngine.execute_liquidation(db, position.id)
                    liquidated_positions.append(liquidated)
                except Exception as e:
                    logger.error(f"[RiskEngine] Liquidation failed: {e}")
        
        if liquidated_positions:
            await db.commit()
            logger.info(
                f"[RiskEngine] Monitor complete: {len(liquidated_positions)} positions liquidated"
            )
        
        return liquidated_positions
    
    @staticmethod
    async def get_positions_risk(
        db: AsyncSession,
        user_id: int,
        price_map: Dict[str, Decimal],
    ) -> List[PositionRisk]:
        """
        获取用户所有仓位的风险数据
        
        用于前端展示实时盈亏
        """
        positions = await PositionManager.get_user_positions(
            db, user_id, PositionStatus.OPEN
        )
        
        risks = []
        for position in positions:
            mark_price = price_map.get(position.symbol, position.entry_price)
            risk = RiskEngine.calculate_position_risk(position, mark_price)
            risks.append(risk)
        
        return risks
