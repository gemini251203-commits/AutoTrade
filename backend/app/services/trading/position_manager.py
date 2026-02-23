"""
Position Manager Service
=========================
仓位管理服务

负责仓位的创建、平仓和管理，确保资金操作的原子性。
"""

from decimal import Decimal
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.position import Position, PositionSide, PositionStatus, MarginMode
from app.services.wallet import WalletManager, InsufficientFundsError
from app.services.margin.calculator import MarginCalculator
from app.services.margin.leverage_tiers import MIN_NOTIONAL_VALUE


class PositionError(Exception):
    """仓位操作异常"""
    pass


class PositionNotFoundError(PositionError):
    """仓位不存在"""
    def __init__(self, position_id: int):
        super().__init__(f"Position not found: {position_id}")


class InsufficientMarginError(PositionError):
    """保证金不足"""
    def __init__(self, required: Decimal, available: Decimal):
        super().__init__(
            f"Insufficient margin: required={required}, available={available}"
        )


class PositionConflictError(PositionError):
    """仓位冲突 - 同一交易对不能同时有多空仓位"""
    def __init__(self, symbol: str, existing_side: str, requested_side: str):
        super().__init__(
            f"Position conflict on {symbol}: cannot open {requested_side} "
            f"while {existing_side} position exists. Close existing position first."
        )


class LeverageExceededError(PositionError):
    """杠杆超过允许范围"""
    def __init__(self, requested: int, max_allowed: int, notional: Decimal):
        self.requested = requested
        self.max_allowed = max_allowed
        self.notional = notional
        super().__init__(
            f"杠杆 {requested}x 超过限制。仓位 {notional:.0f} USDT 最大杠杆为 {max_allowed}x"
        )


class MinNotionalError(PositionError):
    """名义价值低于最小限制"""
    def __init__(self, notional: Decimal, min_required: Decimal = MIN_NOTIONAL_VALUE):
        self.notional = notional
        self.min_required = min_required
        super().__init__(
            f"名义价值 {notional:.2f} USDT 低于最小限制 {min_required} USDT"
        )


class PositionManager:
    """
    仓位管理器
    
    核心方法:
    - open_position: 开仓 (冻结保证金 + 创建仓位)
    - close_position: 平仓 (释放保证金 + 计算盈亏)
    - add_to_position: 加仓 (增加保证金 + 更新均价)
    - reduce_position: 减仓 (部分平仓)
    
    资金一致性保障:
    - 所有操作在单一数据库事务中完成
    - 使用 FOR UPDATE 行锁防止并发冲突
    """
    
    @staticmethod
    def calculate_margin(
        quantity: Decimal,
        price: Decimal,
        leverage: int,
    ) -> Decimal:
        """
        计算所需保证金
        
        保证金 = (数量 × 价格) / 杠杆
        
        例如: 买入 0.1 BTC @ $80,000, 10x 杠杆
        保证金 = (0.1 × 80000) / 10 = 800 USDT
        """
        notional_value = quantity * price
        return notional_value / Decimal(leverage)
    
    @staticmethod
    def calculate_liquidation_price(
        entry_price: Decimal,
        leverage: int,
        side: PositionSide,
        maintenance_margin_rate: Decimal = Decimal("0.004"),  # 0.4%
    ) -> Decimal:
        """
        计算逐仓模式强平价格 (向后兼容)
        
        ⚠️ 此方法仅作为后备使用
        全仓模式请使用 calculate_cross_liquidation_price
        """
        lev = Decimal(leverage)
        one = Decimal("1")
        
        if side == PositionSide.LONG:
            liq_price = entry_price * (one - one/lev + maintenance_margin_rate)
        else:
            liq_price = entry_price * (one + one/lev - maintenance_margin_rate)
        
        return liq_price.quantize(Decimal("0.01"))
    
    @staticmethod
    def calculate_cross_liquidation_price(
        entry_price: Decimal,
        quantity: Decimal,
        account_balance: Decimal,
        unrealized_pnl: Decimal,
        other_positions_margin: Decimal,
        side: PositionSide,
        maintenance_margin_rate: Decimal = Decimal("0.004"),
    ) -> Decimal:
        """
        计算全仓模式强平价格 (动态值)
        
        全仓模式下，账户的所有可用余额（包括未实现盈亏）都作为保证金。
        爆仓价格 = 基于整个钱包余额计算，而非仅该仓位保证金
        
        公式:
        可用保证金 = 账户余额 + 未实现盈亏 - 其他仓位占用
        做多: 强平价 = 开仓价 × (1 - 可用保证金/名义价值 + 维持保证金率)
        做空: 强平价 = 开仓价 × (1 + 可用保证金/名义价值 - 维持保证金率)
        """
        one = Decimal("1")
        
        # 账户总权益
        total_equity = account_balance + unrealized_pnl
        
        # 可用于该仓位的保证金 = 总权益 - 其他仓位保证金
        available_margin = total_equity - other_positions_margin
        
        # 仓位名义价值
        notional = quantity * entry_price
        
        if notional == 0:
            return Decimal("0")
        
        # 保证金比率
        margin_ratio = available_margin / notional
        
        if side == PositionSide.LONG:
            # 全仓做多: 强平价格会更低（因为有更多保证金支撑）
            liq_price = entry_price * (one - margin_ratio + maintenance_margin_rate)
        else:
            # 全仓做空: 强平价格会更高
            liq_price = entry_price * (one + margin_ratio - maintenance_margin_rate)
        
        # 确保强平价不为负
        if liq_price < 0:
            liq_price = Decimal("0")
            
        return liq_price.quantize(Decimal("0.01"))
    
    @staticmethod
    async def open_position(
        db: AsyncSession,
        user_id: int,
        symbol: str,
        side: PositionSide,
        quantity: Decimal,
        entry_price: Decimal,
        leverage: int = 1,
        margin_mode: MarginMode = MarginMode.CROSS,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        source: str = "manual",
        open_reason: Optional[str] = None,
        commission: Decimal = Decimal("0"),
        pre_frozen_margin: Optional[Decimal] = None,
    ) -> Position:
        """
        开仓
        
        流程:
        1. 计算所需保证金
        2. 冻结保证金 (原子操作)
        3. 检查是否有同向仓位 (合并)
        4. 创建仓位记录
        5. 计算强平价格
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            symbol: 交易对
            side: 方向 (long/short)
            quantity: 数量
            entry_price: 开仓价格
            leverage: 杠杆倍数
            margin_mode: 保证金模式
            stop_loss: 止损价 (可选)
            take_profit: 止盈价 (可选)
        
        Returns:
            创建的 Position 实例
        
        Raises:
            InsufficientMarginError: 保证金不足
            LeverageExceededError: 杠杆超过限制
            MinNotionalError: 名义价值低于最小限制
        """
        # 0. 验证杠杆是否符合币安规则
        notional = quantity * entry_price
        
        # 检查最小名义价值
        if notional < MIN_NOTIONAL_VALUE:
            raise MinNotionalError(notional)
        
        # 检查杠杆是否在允许范围内
        is_valid, error_msg, max_leverage = MarginCalculator.validate_order_leverage(
            symbol, quantity, entry_price, leverage
        )
        
        if not is_valid:
            logger.warning(f"[PositionManager] Leverage rejected: {error_msg}")
            raise LeverageExceededError(leverage, max_leverage or 1, notional)
        
        # 1. 计算所需保证金
        margin_required = PositionManager.calculate_margin(
            quantity, entry_price, leverage
        )
        
        logger.info(
            f"[PositionManager] Opening position: user={user_id}, "
            f"{symbol} {side.value} {quantity} @ {entry_price}, "
            f"leverage={leverage}x, margin={margin_required} USDT, "
            f"max_allowed_leverage={max_leverage}x"
        )
        
        # 2. 检查并冻结保证金 (如果 OrderExecutor 已预冻结则跳过)
        if pre_frozen_margin is not None:
            # 已由 OrderExecutor 预冻结, 直接使用
            logger.info(
                f"[PositionManager] Using pre-frozen margin: {pre_frozen_margin} USDT "
                f"(required: {margin_required})"
            )
        else:
            try:
                await WalletManager.freeze_funds(db, user_id, margin_required)
            except InsufficientFundsError as e:
                raise InsufficientMarginError(margin_required, e.available)
        
        # 2.5 检查是否有反向仓位 → 净仓位模式 (减仓/反向)
        opposite_side = PositionSide.SHORT if side == PositionSide.LONG else PositionSide.LONG
        opposite_position = await PositionManager.get_open_position(
            db, user_id, symbol, opposite_side
        )
        
        if opposite_position:
            # 🔥 净仓位模式: 反向订单 = 平掉反向仓位
            # 先释放刚才冻结的保证金 (close_position 会单独处理)
            await WalletManager.unfreeze_funds(db, user_id, margin_required)
            
            if quantity <= opposite_position.size:
                # 情况1: 反向数量 <= 现有仓位 → 部分平仓
                logger.info(
                    f"[PositionManager] Net position: reducing {opposite_side.value} "
                    f"by {quantity} (partial close)"
                )
                updated_pos, pnl = await PositionManager.close_position(
                    db, opposite_position.id, entry_price, quantity, commission=commission
                )
                return updated_pos
            else:
                # 情况2: 反向数量 > 现有仓位 → 全部平仓 + 反向开仓
                remaining_qty = quantity - opposite_position.size
                logger.info(
                    f"[PositionManager] Net position: closing all {opposite_side.value} "
                    f"and opening {side.value} with {remaining_qty}"
                )
                
                # 先全部平仓
                await PositionManager.close_position(
                    db, opposite_position.id, entry_price, commission=commission
                )
                
                # 递归调用开反向仓位 (此时没有反向仓位了)
                return await PositionManager.open_position(
                    db=db,
                    user_id=user_id,
                    symbol=symbol,
                    side=side,
                    quantity=remaining_qty,
                    entry_price=entry_price,
                    leverage=leverage,
                    margin_mode=margin_mode,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    source=source,
                    open_reason=open_reason,
                    commission=Decimal("0"),  # 手续费已在平仓时扣完
                )
        
        # 3. 检查是否有同向仓位
        existing = await PositionManager.get_open_position(
            db, user_id, symbol, side
        )
        
        if existing:
            # 合并仓位 (加权平均价格)
            total_size = existing.size + quantity
            total_notional = (existing.size * existing.entry_price) + (quantity * entry_price)
            new_avg_price = total_notional / total_size
            
            existing.size = total_size
            existing.entry_price = new_avg_price
            existing.margin += margin_required
            existing.leverage = leverage  # 更新杠杆
            existing.total_commission += commission  # 🔥 累加手续费
            
            # 🔥 全仓模式: 使用钱包余额计算强平价
            wallet = await WalletManager.get_or_create_wallet(db, user_id)
            account_balance = wallet.balance + wallet.frozen
            existing.liquidation_price = PositionManager.calculate_cross_liquidation_price(
                entry_price=new_avg_price,
                quantity=total_size,
                account_balance=account_balance,
                unrealized_pnl=Decimal("0"),  # 开仓时无未实现盈亏
                other_positions_margin=Decimal("0"),  # 简化: 仅考虑当前仓位
                side=side,
            )
            
            if stop_loss:
                existing.stop_loss = stop_loss
            if take_profit:
                existing.take_profit = take_profit
            
            logger.info(
                f"[PositionManager] Merged into existing position: "
                f"id={existing.id}, total_size={total_size}, avg_price={new_avg_price}"
            )
            
            return existing
        
        # 4. 创建新仓位
        # 🔥 全仓模式: 使用钱包余额计算强平价
        wallet = await WalletManager.get_or_create_wallet(db, user_id)
        account_balance = wallet.balance + wallet.frozen
        liquidation_price = PositionManager.calculate_cross_liquidation_price(
            entry_price=entry_price,
            quantity=quantity,
            account_balance=account_balance,
            unrealized_pnl=Decimal("0"),  # 开仓时无未实现盈亏
            other_positions_margin=Decimal("0"),  # 简化: 仅考虑单一仓位
            side=side,
        )
        
        position = Position(
            user_id=user_id,
            symbol=symbol,
            side=side,
            status=PositionStatus.OPEN,
            size=quantity,
            entry_price=entry_price,
            leverage=leverage,
            margin=margin_required,
            margin_mode=margin_mode,
            liquidation_price=liquidation_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=source,
            open_reason=open_reason,
            total_commission=commission,
        )
        
        db.add(position)
        await db.flush()
        
        logger.info(
            f"[PositionManager] Position opened: id={position.id}, "
            f"liq_price={liquidation_price}"
        )
        
        return position
    
    @staticmethod
    async def close_position(
        db: AsyncSession,
        position_id: int,
        close_price: Decimal,
        close_quantity: Optional[Decimal] = None,
        commission: Decimal = Decimal("0"),
    ) -> tuple[Position, Decimal]:
        """
        平仓
        
        流程:
        1. 获取仓位 (加锁)
        2. 计算已实现盈亏
        3. 扣除手续费
        4. 释放保证金 + 结算盈亏
        5. 更新仓位状态
        
        Args:
            db: 数据库会话
            position_id: 仓位 ID
            close_price: 平仓价格
            close_quantity: 平仓数量 (None = 全平)
            commission: 平仓手续费 (USDT)
        
        Returns:
            (更新后的仓位, 已实现盈亏 - 净值, 已扣手续费)
        """
        # 1. 获取仓位
        result = await db.execute(
            select(Position)
            .where(Position.id == position_id)
            .with_for_update()
        )
        position = result.scalar_one_or_none()
        
        if not position:
            raise PositionNotFoundError(position_id)
        
        if position.status != PositionStatus.OPEN:
            raise PositionError(f"Position already closed: {position.status.value}")
        
        # 确定平仓数量
        if close_quantity is None or close_quantity >= position.size:
            close_quantity = position.size
            is_full_close = True
        else:
            is_full_close = False
        
        # 2. 计算已实现盈亏 (原始, 不含手续费)
        raw_pnl = position.calculate_unrealized_pnl(close_price)
        if not is_full_close:
            # 部分平仓: 按比例计算
            raw_pnl = raw_pnl * (close_quantity / position.size)
        
        # 🔥 3. 扣除平仓手续费 → 净 P&L
        # ⚠️ 语义: realized_pnl = 净值 (已扣手续费), 前端不应再减 total_commission
        pnl = raw_pnl - commission
        
        # 3. 计算释放的保证金
        if is_full_close:
            margin_to_release = position.margin
        else:
            margin_to_release = position.margin * (close_quantity / position.size)
        
        logger.info(
            f"[PositionManager] Closing position: id={position_id}, "
            f"quantity={close_quantity}, price={close_price}, "
            f"raw_pnl={raw_pnl}, commission={commission}, "
            f"net_pnl={pnl}, margin_release={margin_to_release}"
        )
        
        # 4. 结算资金 (用净 P&L)
        await WalletManager.settle_pnl(
            db, 
            position.user_id, 
            pnl, 
            margin_to_release,
        )
        
        # 5. 更新仓位
        position.total_commission += commission
        
        if is_full_close:
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.utcnow()
            position.realized_pnl = pnl
            
            # 🔥 统一记忆: 平仓时自动生成交易记忆
            try:
                from app.services.trade_journal import TradeJournal
                # close_reason 从 position.source 推断
                close_reason = getattr(position, "source", "manual") or "manual"
                await TradeJournal.record_close(
                    db=db,
                    position=position,
                    pnl=pnl,
                    close_price=close_price,
                    close_reason=close_reason,
                )
            except Exception as e:
                logger.warning(f"[PositionManager] TradeJournal 记录失败 (不影响平仓): {e}")
        else:
            position.size -= close_quantity
            position.margin -= margin_to_release
            position.realized_pnl += pnl
        
        return position, pnl
    
    @staticmethod
    async def get_open_position(
        db: AsyncSession,
        user_id: int,
        symbol: str,
        side: PositionSide,
    ) -> Optional[Position]:
        """获取用户在指定交易对和方向的开放仓位"""
        result = await db.execute(
            select(Position).where(
                and_(
                    Position.user_id == user_id,
                    Position.symbol == symbol,
                    Position.side == side,
                    Position.status == PositionStatus.OPEN,
                )
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_positions(
        db: AsyncSession,
        user_id: int,
        status: Optional[PositionStatus] = None,
    ) -> List[Position]:
        """获取用户所有仓位"""
        query = select(Position).where(Position.user_id == user_id)
        
        if status:
            query = query.where(Position.status == status)
        
        query = query.order_by(Position.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def liquidate_position(
        db: AsyncSession,
        position_id: int,
    ) -> Position:
        """
        强制平仓
        
        当标记价格触及强平价时调用，
        以强平价格全部平仓。
        """
        result = await db.execute(
            select(Position)
            .where(Position.id == position_id)
            .with_for_update()
        )
        position = result.scalar_one_or_none()
        
        if not position:
            raise PositionNotFoundError(position_id)
        
        logger.warning(
            f"[PositionManager] LIQUIDATING position: id={position_id}, "
            f"symbol={position.symbol}, side={position.side.value}"
        )
        
        # 🔥 强平手续费 (使用 FeeCalculator 的清算费率)
        from app.services.trading.fee_calculator import FeeCalculator
        liq_commission = (
            position.size * position.liquidation_price * FeeCalculator.LIQUIDATION_FEE_RATE
        )
        
        # 以强平价格平仓
        _, pnl = await PositionManager.close_position(
            db, position_id, position.liquidation_price, commission=liq_commission
        )
        
        # 更新状态为已强平
        position.status = PositionStatus.LIQUIDATED
        
        return position
    
    @staticmethod
    async def update_all_liquidation_prices(
        db: AsyncSession,
        user_id: int,
        current_prices: dict[str, Decimal],
    ) -> int:
        """
        更新用户所有仓位的强平价格 (全仓模式)
        
        全仓模式下，强平价格会随钱包余额变化而动态更新。
        此方法应在以下情况调用:
        - 价格变动时 (影响未实现盈亏)
        - 钱包余额变动时 (充值/提现/开新仓)
        - 定期刷新 (如每分钟一次)
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            current_prices: 各交易对当前价格 {"BTCUSDT": 78000, ...}
            
        Returns:
            更新的仓位数量
        """
        # 1. 获取钱包余额
        wallet = await WalletManager.get_or_create_wallet(db, user_id)
        account_balance = wallet.balance + wallet.frozen
        
        # 2. 获取所有开放仓位
        positions = await PositionManager.get_user_positions(
            db, user_id, PositionStatus.OPEN
        )
        
        if not positions:
            return 0
        
        # 3. 计算总未实现盈亏
        total_unrealized_pnl = Decimal("0")
        for pos in positions:
            current_price = current_prices.get(pos.symbol)
            if current_price:
                if pos.side == PositionSide.LONG:
                    pnl = (current_price - pos.entry_price) * pos.size
                else:
                    pnl = (pos.entry_price - current_price) * pos.size
                total_unrealized_pnl += pnl
        
        # 4. 计算其他仓位占用的保证金总和
        total_margin = sum(pos.margin for pos in positions)
        
        # 5. 更新每个仓位的强平价格
        updated_count = 0
        for pos in positions:
            other_margin = total_margin - pos.margin
            
            new_liq_price = PositionManager.calculate_cross_liquidation_price(
                entry_price=pos.entry_price,
                quantity=pos.size,
                account_balance=account_balance,
                unrealized_pnl=total_unrealized_pnl,
                other_positions_margin=other_margin,
                side=pos.side,
            )
            
            if pos.liquidation_price != new_liq_price:
                pos.liquidation_price = new_liq_price
                updated_count += 1
                logger.debug(
                    f"[PositionManager] Updated liq_price: {pos.symbol} {pos.side.value} "
                    f"-> {new_liq_price}"
                )
        
        return updated_count

