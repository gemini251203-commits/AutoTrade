"""
Wallet API
===========
钱包相关端点 (生产版)

⚠️ 安全原则:
- 只有 POST /initialize 可以创建/重置钱包
- GET 接口只做懒加载初始化，不会修改现有余额
"""

from datetime import datetime, timezone

from decimal import Decimal
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.wallet import Wallet
from app.services.wallet import WalletManager
from app.core.time_utils import utc_now
from sqlalchemy import select, func


router = APIRouter()


# ==================== Schemas ====================

class WalletResponse(BaseModel):
    """钱包信息响应"""
    user_id: int
    balance: Decimal
    frozen: Decimal
    total_pnl: Decimal
    
    class Config:
        from_attributes = True


class WalletBalanceResponse(BaseModel):
    """余额查询响应"""
    available: Decimal
    frozen: Decimal
    total_equity: Decimal
    total_pnl: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    funding_balance: Decimal = Decimal("0")
    initial_balance: Decimal = Decimal("0")  # 总投入本金 (充值+初始化)


# ==================== Routes ====================

@router.get("/", response_model=WalletResponse)
async def get_wallet(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取当前用户钱包
    
    懒加载: 如果钱包不存在，自动初始化
    安全: 绝不修改现有余额
    """
    wallet = await WalletManager.get_wallet(db, current_user.id)
    
    if not wallet:
        # 钱包不存在，初始化新钱包 (WalletManager 决定初始金额)
        wallet = await WalletManager.initialize_wallet(db, current_user.id)
        await db.commit()
        logger.info(f"[Wallet] Auto-initialized wallet for user {current_user.id}: {wallet.balance} USDT")
    
    return wallet


@router.get("/balance", response_model=WalletBalanceResponse)
async def get_balance(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取余额详情
    
    懒加载: 如果钱包不存在，自动初始化
    安全: 绝不修改现有余额
    包含: unrealized_pnl (从持仓实时计算)
    """
    from sqlalchemy import select
    from app.models.position import Position, PositionStatus, PositionSide
    from app.services.exchange import BinanceClient

    wallet = await WalletManager.get_wallet(db, current_user.id)
    
    if not wallet:
        # 钱包不存在，初始化
        wallet = await WalletManager.initialize_wallet(db, current_user.id)
        await db.commit()
        await db.refresh(wallet)
        logger.info(f"[Wallet] Auto-initialized wallet for user {current_user.id}: {wallet.balance} USDT")
    
    # 计算未实现盈亏: 从所有 open positions 获取 (并发查询)
    unrealized_pnl = Decimal("0")
    try:
        result = await db.execute(
            select(Position).where(
                Position.user_id == current_user.id,
                Position.status == PositionStatus.OPEN,
            )
        )
        open_positions = result.scalars().all()
        
        if open_positions:
            import asyncio
            client = BinanceClient()

            async def _calc_pnl(pos):
                try:
                    ticker = await client.get_ticker(pos.symbol)
                    price = Decimal(str(ticker.get("lastPrice", 0))) if ticker else Decimal("0")
                    return pos.calculate_unrealized_pnl(price) if price > 0 else Decimal("0")
                except Exception:
                    return Decimal("0")

            results = await asyncio.gather(*[_calc_pnl(p) for p in open_positions])
            unrealized_pnl = sum(results, Decimal("0"))
    except Exception as e:
        logger.warning(f"[Wallet] Failed to calculate unrealized PnL: {e}")
    
    # 🔥 冻结台账审计: 校验 wallet.frozen 是否与活跃订单+持仓保证金一致
    try:
        from app.models.order import Order, OrderStatus as OrdStatus
        
        # 活跃订单的冻结金额总和
        order_result = await db.execute(
            select(Order).where(
                Order.user_id == current_user.id,
                Order.status.in_([OrdStatus.PENDING, OrdStatus.OPEN]),
            )
        )
        active_orders = order_result.scalars().all()
        orders_frozen = sum((o.frozen_amount for o in active_orders), Decimal("0"))
        
        # 持仓保证金总和
        positions_margin = sum((p.margin for p in open_positions), Decimal("0")) if open_positions else Decimal("0")
        
        expected_frozen = orders_frozen + positions_margin
        actual_frozen = wallet.frozen
        
        drift = abs(actual_frozen - expected_frozen)
        if drift > Decimal("0.01"):
            logger.critical(
                f"[FROZEN AUDIT] MISMATCH! user={current_user.id}, "
                f"wallet.frozen={actual_frozen}, expected={expected_frozen} "
                f"(orders={orders_frozen}, positions={positions_margin}, "
                f"drift={drift})"
            )
        else:
            logger.debug(f"[FROZEN AUDIT] OK: frozen={actual_frozen}, expected={expected_frozen}")
    except Exception as e:
        logger.warning(f"[FROZEN AUDIT] Check failed: {e}")
    
    # 计算总投入本金: deposit + reset 的总和
    initial_balance = Decimal("0")
    try:
        from app.models.wallet_transaction import WalletTransaction, TransactionType
        deposit_q = await db.execute(
            select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
                WalletTransaction.user_id == current_user.id,
                WalletTransaction.type.in_([
                    TransactionType.DEPOSIT.value,
                    TransactionType.RESET.value,
                ]),
            )
        )
        initial_balance = deposit_q.scalar() or Decimal("0")
    except Exception as e:
        logger.warning(f"[Wallet] Failed to calculate initial_balance: {e}")
    
    return WalletBalanceResponse(
        available=wallet.balance,
        frozen=wallet.frozen,
        total_equity=wallet.total_equity,
        total_pnl=wallet.total_pnl,
        unrealized_pnl=unrealized_pnl,
        funding_balance=wallet.funding_balance,
        initial_balance=initial_balance,
    )


@router.post("/initialize", response_model=WalletResponse)
async def initialize_wallet(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    初始化钱包 (模拟模式会空投初始资金)
    
    行为:
    - 如果钱包不存在: 创建新钱包，空投初始资金
    - 如果钱包已存在: 直接返回现有钱包 (不修改余额)
    """
    wallet = await WalletManager.get_wallet(db, current_user.id)
    
    if wallet:
        # 钱包已存在，直接返回 (不修改任何数据)
        logger.debug(f"[Wallet] Wallet already exists for user {current_user.id}")
        return wallet
    
    # 创建新钱包
    wallet = await WalletManager.initialize_wallet(db, current_user.id)
    await db.commit()
    await db.refresh(wallet)
    logger.info(f"[Wallet] Created new wallet for user {current_user.id}: {wallet.balance} USDT")
    
    return wallet


class TransferRequest(BaseModel):
    """划转请求"""
    amount: Decimal
    direction: str  # "to_funding" | "to_contract"


class TransferResponse(BaseModel):
    """划转响应"""
    success: bool
    contract_balance: Decimal
    funding_balance: Decimal
    message: str


@router.post("/transfer", response_model=TransferResponse)
async def transfer_funds(
    current_user: CurrentUser,
    db: DbSession,
    req: TransferRequest,
):
    """
    合约账户 ↔ 资金账户 划转
    
    direction:
    - "to_funding": 合约 → 资金
    - "to_contract": 资金 → 合约
    """
    from app.services.wallet.manager import InsufficientFundsError
    
    try:
        wallet = await WalletManager.transfer_funds(
            db, current_user.id, req.amount, req.direction
        )
        await db.commit()
        await db.refresh(wallet)
        
        # 划转后重算爆仓价 (余额变化影响全仓爆仓价)
        try:
            from app.services.trading.position_manager import PositionManager
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            prices = await client.get_all_tickers()
            price_map = {t['symbol']: Decimal(str(t['price'])) for t in (prices or [])}
            await PositionManager.update_all_liquidation_prices(
                db, current_user.id, price_map
            )
            await db.commit()
        except Exception as e:
            logger.warning(f"[Wallet] Failed to update liquidation prices after transfer: {e}")
        
        direction_label = "合约→资金" if req.direction == "to_funding" else "资金→合约"
        return TransferResponse(
            success=True,
            contract_balance=wallet.balance,
            funding_balance=wallet.funding_balance,
            message=f"{direction_label} 划转 {req.amount} USDT 成功",
        )
    except InsufficientFundsError as e:
        raise HTTPException(status_code=400, detail=f"余额不足: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Portfolio Stats ====================

class DailyPnlItem(BaseModel):
    """每日盈亏"""
    date: str
    pnl: float

class TradeSummary(BaseModel):
    """交易摘要"""
    total_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    total_volume: float = 0.0
    long_volume: float = 0.0
    short_volume: float = 0.0
    total_commission: float = 0.0
    latest_commission: float = 0.0

class PortfolioStatsResponse(BaseModel):
    """投资组合统计响应"""
    total_value: float
    pnl_7d: float
    volume_7d: float
    perpetual_count: int
    daily_pnl: list[DailyPnlItem]
    summary: TradeSummary
    taker_fee_rate: str = "0.05%"
    maker_fee_rate: str = "0.02%"


@router.get("/portfolio-stats", response_model=PortfolioStatsResponse)
async def get_portfolio_stats(
    current_user: CurrentUser,
    db: DbSession,
    period: str = "7d",  # 24h, 7d, 14d, 30d, all
):
    """
    投资组合统计

    返回:
    - 总价值、近7天PnL、交易量
    - 日历PnL (当月每日已实现盈亏)
    - 交易摘要 (按时间范围筛选)
    - 吃单/挂单费率
    """
    from sqlalchemy import select, func, case, and_, extract
    from app.models.position import Position, PositionSide, PositionStatus
    import calendar as cal_module
    from datetime import timedelta

    now = utc_now()

    # ---------- 1. 总价值 ----------
    wallet = await WalletManager.get_wallet(db, current_user.id)
    if not wallet:
        wallet = await WalletManager.initialize_wallet(db, current_user.id)
        await db.commit()

    total_value = float(wallet.balance) + float(wallet.frozen)

    # ---------- 2. 永续合约持仓数 ----------
    open_count_q = await db.execute(
        select(func.count()).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.OPEN,
        )
    )
    perpetual_count = open_count_q.scalar() or 0

    # ---------- 3. 7天 PnL 和交易量 ----------
    seven_days_ago = now - timedelta(days=7)
    pnl_7d_q = await db.execute(
        select(
            func.coalesce(func.sum(Position.realized_pnl), 0),
            func.coalesce(func.sum(Position.size * Position.entry_price), 0),
        ).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.CLOSED,
            Position.closed_at >= seven_days_ago,
        )
    )
    row = pnl_7d_q.one()
    pnl_7d = float(row[0])
    volume_7d = float(row[1])

    # ---------- 4. 日历 PnL (当月, 北京时间 UTC+8) ----------
    from datetime import timedelta as td
    beijing_offset = td(hours=8)
    now_beijing = now + beijing_offset
    first_day = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, last_day_num = cal_module.monthrange(now_beijing.year, now_beijing.month)
    last_day = first_day.replace(day=last_day_num, hour=23, minute=59, second=59)
    # 转回 UTC 进行 DB 查询
    first_day_utc = first_day - beijing_offset
    last_day_utc = last_day - beijing_offset

    # 使用数据库层面的时区偏移: closed_at + 8h → 按北京日期分组
    from sqlalchemy import literal_column, text
    beijing_interval = text("INTERVAL '8 hours'")
    daily_pnl_q = await db.execute(
        select(
            func.date(Position.closed_at + beijing_interval).label("day"),
            func.sum(Position.realized_pnl).label("pnl"),
        ).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.CLOSED,
            Position.closed_at >= first_day_utc,
            Position.closed_at <= last_day_utc,
        ).group_by(func.date(Position.closed_at + beijing_interval))
    )
    daily_pnl_map = {str(r.day): float(r.pnl) for r in daily_pnl_q.all()}

    # 填充完整月份 (北京时间月份)
    daily_pnl_list = []
    for d in range(1, last_day_num + 1):
        date_str = f"{now_beijing.year}-{now_beijing.month:02d}-{d:02d}"
        daily_pnl_list.append(DailyPnlItem(
            date=date_str,
            pnl=daily_pnl_map.get(date_str, 0.0),
        ))

    # ---------- 5. 交易摘要 (按时间范围) ----------
    period_map = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "14d": timedelta(days=14),
        "30d": timedelta(days=30),
    }

    filters = [
        Position.user_id == current_user.id,
        Position.status == PositionStatus.CLOSED,
    ]
    if period != "all" and period in period_map:
        cutoff = now - period_map[period]
        filters.append(Position.closed_at >= cutoff)

    summary_q = await db.execute(
        select(
            func.count().label("total"),
            func.count(case(
                (Position.side == PositionSide.LONG, 1),
            )).label("long_count"),
            func.count(case(
                (Position.side == PositionSide.SHORT, 1),
            )).label("short_count"),
            func.coalesce(func.sum(Position.size * Position.entry_price), 0).label("total_vol"),
            func.coalesce(func.sum(case(
                (Position.side == PositionSide.LONG, Position.size * Position.entry_price),
                else_=0,
            )), 0).label("long_vol"),
            func.coalesce(func.sum(case(
                (Position.side == PositionSide.SHORT, Position.size * Position.entry_price),
                else_=0,
            )), 0).label("short_vol"),
            func.coalesce(func.sum(Position.total_commission), 0).label("total_comm"),
        ).where(*filters)
    )
    s = summary_q.one()

    # 最近一笔手续费
    latest_q = await db.execute(
        select(Position.total_commission).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.CLOSED,
        ).order_by(Position.closed_at.desc()).limit(1)
    )
    latest_comm = latest_q.scalar() or 0

    summary = TradeSummary(
        total_trades=s.total,
        long_trades=s.long_count,
        short_trades=s.short_count,
        total_volume=float(s.total_vol),
        long_volume=float(s.long_vol),
        short_volume=float(s.short_vol),
        total_commission=float(s.total_comm),
        latest_commission=float(latest_comm),
    )

    return PortfolioStatsResponse(
        total_value=total_value,
        pnl_7d=pnl_7d,
        volume_7d=volume_7d,
        perpetual_count=perpetual_count,
        daily_pnl=daily_pnl_list,
        summary=summary,
    )


# ==================== Transaction Endpoints ====================

class TransactionResponse(BaseModel):
    """流水记录响应"""
    id: int
    type: str
    amount: Decimal
    balance_after: Decimal
    note: str | None
    created_at: datetime
    
    class Config:
        from_attributes = True


class DepositRequest(BaseModel):
    """充值请求"""
    amount: Decimal


class ResetRequest(BaseModel):
    """重置请求 (可选指定初始金额)"""
    initial_balance: Decimal | None = None


@router.get("/transactions", response_model=list[TransactionResponse])
async def get_transactions(
    current_user: CurrentUser,
    db: DbSession,
    limit: int = 50,
    offset: int = 0,
):
    """
    获取资金流水记录
    
    按时间倒序返回用户的资金变动历史
    """
    from sqlalchemy import select
    from app.models.wallet_transaction import WalletTransaction
    
    result = await db.execute(
        select(WalletTransaction)
        .where(WalletTransaction.user_id == current_user.id)
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    transactions = result.scalars().all()
    
    return transactions


@router.post("/deposit", response_model=WalletResponse)
async def deposit(
    current_user: CurrentUser,
    db: DbSession,
    req: DepositRequest,
):
    """
    充值 (仅模拟盘)
    
    向钱包充入模拟资金
    """
    from app.models.wallet_transaction import WalletTransaction, TransactionType
    
    if req.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be positive"
        )
    
    wallet = await WalletManager.get_wallet(db, current_user.id)
    if not wallet:
        wallet = await WalletManager.initialize_wallet(db, current_user.id)
    
    # 增加余额
    wallet.balance += req.amount
    
    # 记录流水
    tx = WalletTransaction(
        user_id=current_user.id,
        type=TransactionType.DEPOSIT.value,
        amount=req.amount,
        balance_after=wallet.balance,
        note=f"Deposit {req.amount} USDT",
    )
    db.add(tx)
    
    await db.commit()
    await db.refresh(wallet)
    
    logger.info(f"[Wallet] User {current_user.id} deposited {req.amount} USDT")
    return wallet


@router.post("/reset", response_model=WalletResponse)
async def reset_wallet(
    current_user: CurrentUser,
    db: DbSession,
    req: ResetRequest | None = None,
):
    """
    重置账户 (仅模拟盘)
    
    将账户完全重置到初始化状态:
    - 删除所有订单、仓位、网格机器人
    - 删除策略日志 (保留策略定义)、自动交易日志
    - 删除所有AI对话、新闻监控规则、AI分析记事本
    - 删除所有趋势分析快照
    - 重置钱包余额
    """
    from app.services.wallet.reset_service import ResetService
    
    initial = req.initial_balance if (req and req.initial_balance) else None
    
    try:
        wallet = await ResetService.full_reset(
            db=db,
            user_id=current_user.id,
            initial_balance=initial,
        )
        return wallet
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"账户重置失败: {str(e)}",
        )


# ==================== Admin: Fix Frozen Funds ====================

@router.post("/fix-frozen", summary="修复冻结金额")
async def fix_frozen_funds(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    修复冻结金额: 如果没有活跃订单/持仓, 将冻结归零
    
    修复因双重冻结 bug 导致的冻结金额不一致
    """
    from app.models.order import Order, OrderStatus
    from sqlalchemy import select, func
    
    user_id = current_user.id
    
    # 1. 获取当前钱包
    wallet = await WalletManager.get_wallet(db, user_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="钱包不存在")
    
    old_frozen = wallet.frozen
    
    # 2. 计算活跃订单冻结金额
    result = await db.execute(
        select(func.coalesce(func.sum(Order.frozen_margin), 0)).where(
            Order.user_id == user_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIAL]),
        )
    )
    orders_frozen = result.scalar() or Decimal("0")
    
    # 3. 计算活跃持仓保证金
    from app.models.position import Position, PositionStatus
    pos_result = await db.execute(
        select(func.coalesce(func.sum(Position.margin), 0)).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    positions_margin = pos_result.scalar() or Decimal("0")
    
    expected_frozen = orders_frozen + positions_margin
    
    # 4. 如果实际冻结与期望不符，修正
    if old_frozen != expected_frozen:
        diff = old_frozen - expected_frozen
        wallet.frozen = expected_frozen
        wallet.balance = wallet.balance + diff
        await db.commit()
        await db.refresh(wallet)
        logger.warning(
            f"[Wallet] Fixed frozen for user {user_id}: "
            f"{old_frozen} -> {expected_frozen} "
            f"(orders={orders_frozen}, positions={positions_margin}, returned {diff})"
        )
        return {
            "message": f"冻结金额已修复: {old_frozen} -> {expected_frozen}",
            "old_frozen": str(old_frozen),
            "new_frozen": str(expected_frozen),
            "orders_frozen": str(orders_frozen),
            "positions_margin": str(positions_margin),
            "returned": str(diff),
            "new_balance": str(wallet.balance),
        }
    
    return {
        "message": f"冻结金额正常: {old_frozen} USDT (订单={orders_frozen}, 持仓={positions_margin})",
        "old_frozen": str(old_frozen),
        "orders_frozen": str(orders_frozen),
        "positions_margin": str(positions_margin),
        "balance": str(wallet.balance),
    }


@router.get("/audit")
async def audit_wallet(
    current_user: CurrentUser,
    db: DbSession,
    fix: bool = False,
):
    """
    钱包审计 — 检查 wallet 余额与实际数据是否一致
    
    公式:
      correct_total = deposits + funding_fees + sum(closed positions realized_pnl)
      correct_frozen = sum(open positions margin) + sum(open orders frozen_amount)
      correct_balance = correct_total - correct_frozen
      correct_total_pnl = sum(closed positions realized_pnl)
    
    参数:
      fix: 如果 True, 自动修正 wallet 到正确值
    """
    from app.models.position import Position
    from app.models.order import Order
    from app.models.wallet_transaction import WalletTransaction
    
    user_id = current_user.id
    wallet = await WalletManager.get_wallet(db, user_id, for_update=fix)
    if not wallet:
        raise HTTPException(status_code=404, detail="钱包不存在")
    
    # 1. 充值总额
    dep_result = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0))
        .where(WalletTransaction.user_id == user_id, WalletTransaction.type == "DEPOSIT")
    )
    deposits = dep_result.scalar() or Decimal("0")
    
    # 2. 资金费率收入
    fund_result = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0))
        .where(WalletTransaction.user_id == user_id, WalletTransaction.type == "FUNDING")
    )
    funding = fund_result.scalar() or Decimal("0")
    
    # 3. 初始化余额 (simulation airdrop)
    init_result = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0))
        .where(WalletTransaction.user_id == user_id, WalletTransaction.type == "INIT")
    )
    init_balance = init_result.scalar() or Decimal("0")
    
    # 4. 已平仓 PNL
    pnl_result = await db.execute(
        select(
            func.coalesce(func.sum(Position.realized_pnl), 0),
            func.count(Position.id),
        )
        .where(
            Position.user_id == user_id,
            Position.status.in_(["CLOSED", "closed", "LIQUIDATED", "liquidated"]),
        )
    )
    pnl_row = pnl_result.one()
    closed_pnl = pnl_row[0] or Decimal("0")
    closed_count = pnl_row[1]
    
    # 5. 开仓保证金
    open_pos_result = await db.execute(
        select(
            func.coalesce(func.sum(Position.margin), 0),
            func.count(Position.id),
        )
        .where(
            Position.user_id == user_id,
            Position.status.in_(["OPEN", "open"]),
        )
    )
    open_pos_row = open_pos_result.one()
    open_positions_margin = open_pos_row[0] or Decimal("0")
    open_positions_count = open_pos_row[1]
    
    # 6. 挂单冻结
    open_ord_result = await db.execute(
        select(func.coalesce(func.sum(Order.frozen_amount), 0))
        .where(
            Order.user_id == user_id,
            Order.status.in_(["OPEN", "open"]),
        )
    )
    open_orders_frozen = open_ord_result.scalar() or Decimal("0")
    
    # 7. 计算正确值
    correct_total = deposits + init_balance + funding + closed_pnl
    correct_frozen = open_positions_margin + open_orders_frozen
    correct_balance = correct_total - correct_frozen
    correct_total_pnl = closed_pnl
    
    actual_total = wallet.balance + wallet.frozen
    diff = actual_total - correct_total
    
    audit = {
        "user_id": user_id,
        "deposits": round(float(deposits), 2),
        "init_balance": round(float(init_balance), 2),
        "funding_income": round(float(funding), 4),
        "closed_pnl": round(float(closed_pnl), 4),
        "closed_count": closed_count,
        "correct_total_funds": round(float(correct_total), 4),
        "open_positions_margin": round(float(open_positions_margin), 2),
        "open_positions_count": open_positions_count,
        "open_orders_frozen": round(float(open_orders_frozen), 2),
        "correct_frozen": round(float(correct_frozen), 2),
        "correct_balance": round(float(correct_balance), 4),
        "correct_total_pnl": round(float(correct_total_pnl), 4),
        "actual_balance": round(float(wallet.balance), 4),
        "actual_frozen": round(float(wallet.frozen), 4),
        "actual_total": round(float(actual_total), 4),
        "actual_total_pnl": round(float(wallet.total_pnl), 4),
        "diff": round(float(diff), 4),
        "is_healthy": abs(diff) < Decimal("0.01"),
    }
    
    if fix and abs(diff) >= Decimal("0.01"):
        old = {
            "balance": round(float(wallet.balance), 2),
            "frozen": round(float(wallet.frozen), 2),
            "total_pnl": round(float(wallet.total_pnl), 2),
        }
        wallet.balance = correct_balance
        wallet.frozen = correct_frozen
        wallet.total_pnl = correct_total_pnl
        await db.commit()
        await db.refresh(wallet)
        audit["fixed"] = True
        audit["old_values"] = old
        audit["message"] = f"已修正: diff={round(float(diff), 2)} USDT"
        logger.warning(
            f"[Wallet Audit] User {user_id}: FIXED wallet. "
            f"diff={diff}, old={old}, "
            f"new=balance={correct_balance}, frozen={correct_frozen}"
        )
    elif fix:
        audit["fixed"] = False
        audit["message"] = "钱包数据一致，无需修正"
    
    return audit

