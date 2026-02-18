"""
Wallet API
===========
钱包相关端点 (生产版)

⚠️ 安全原则:
- 只有 POST /initialize 可以创建/重置钱包
- GET 接口只做懒加载初始化，不会修改现有余额
"""

from datetime import datetime

from decimal import Decimal
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.models.wallet import Wallet
from app.services.wallet import WalletManager


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
    
    return WalletBalanceResponse(
        available=wallet.balance,
        frozen=wallet.frozen,
        total_equity=wallet.total_equity,
        total_pnl=wallet.total_pnl,
        unrealized_pnl=unrealized_pnl,
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


@router.get("/portfolio-stats")
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

    now = datetime.utcnow()

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

    # ---------- 4. 日历 PnL (当月) ----------
    first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, last_day_num = cal_module.monthrange(now.year, now.month)
    last_day = first_day.replace(day=last_day_num, hour=23, minute=59, second=59)

    daily_pnl_q = await db.execute(
        select(
            func.date(Position.closed_at).label("day"),
            func.sum(Position.realized_pnl).label("pnl"),
        ).where(
            Position.user_id == current_user.id,
            Position.status == PositionStatus.CLOSED,
            Position.closed_at >= first_day,
            Position.closed_at <= last_day,
        ).group_by(func.date(Position.closed_at))
    )
    daily_pnl_map = {str(r.day): float(r.pnl) for r in daily_pnl_q.all()}

    # 填充完整月份
    daily_pnl_list = []
    for d in range(1, last_day_num + 1):
        date_str = f"{now.year}-{now.month:02d}-{d:02d}"
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
    
    将账户完全重置:
    - 删除所有订单
    - 删除所有仓位
    - 删除所有网格机器人
    - 删除所有AI任务
    - 重置钱包余额
    """
    from sqlalchemy import delete
    from app.models.wallet_transaction import WalletTransaction, TransactionType
    from app.models.order import Order
    from app.models.position import Position
    from app.models.grid_bot import GridBot
    from app.models.task import TaskTicket
    import os
    
    user_id = current_user.id
    
    logger.info(f"[Wallet] User {user_id} starting full account reset...")
    
    # 1. 删除所有订单
    await db.execute(
        delete(Order).where(Order.user_id == user_id)
    )
    logger.info(f"[Wallet] Deleted all orders for user {user_id}")
    
    # 2. 删除所有仓位
    await db.execute(
        delete(Position).where(Position.user_id == user_id)
    )
    logger.info(f"[Wallet] Deleted all positions for user {user_id}")
    
    # 3. 删除所有网格机器人
    await db.execute(
        delete(GridBot).where(GridBot.user_id == user_id)
    )
    logger.info(f"[Wallet] Deleted all grid bots for user {user_id}")
    
    # 4. 删除所有AI任务
    await db.execute(
        delete(TaskTicket).where(TaskTicket.user_id == user_id)
    )
    logger.info(f"[Wallet] Deleted all AI tasks for user {user_id}")
    
    # 5. 删除所有交易记忆 (Trade Journal)
    from app.models.strategy import TradeMemory
    await db.execute(
        delete(TradeMemory).where(TradeMemory.user_id == user_id)
    )
    logger.info(f"[Wallet] Deleted all trade memories for user {user_id}")
    
    # 6. 删除所有流水记录
    await db.execute(
        delete(WalletTransaction).where(WalletTransaction.user_id == user_id)
    )
    logger.info(f"[Wallet] Deleted all transactions for user {user_id}")
    
    # 6. 重置钱包
    initial = req.initial_balance if (req and req.initial_balance) else Decimal(
        os.getenv("SIMULATION_INITIAL_BALANCE", "100")  # 🔥 改为 100U
    )
    
    wallet = await WalletManager.get_wallet(db, user_id)
    if not wallet:
        wallet = await WalletManager.initialize_wallet(db, user_id)
    
    # 记录重置前余额
    old_balance = wallet.balance + wallet.frozen
    
    wallet.balance = initial
    wallet.frozen = Decimal("0")
    wallet.total_pnl = Decimal("0")
    
    # 记录重置流水
    tx = WalletTransaction(
        user_id=user_id,
        type=TransactionType.RESET.value,
        amount=initial,
        balance_after=initial,
        note=f"Full account reset to {initial} USDT (was {old_balance} USDT)",
    )
    db.add(tx)
    
    # 🔥 记录到交易日志 (让 journal 页面对账)
    from app.models.strategy import TradeMemory
    journal_entry = TradeMemory(
        user_id=user_id,
        symbol="ACCOUNT",
        source="system",
        trade_result="breakeven",
        pnl_pct=0,
        pnl_usdt=float(initial - old_balance),
        close_reason="account_reset",
        open_reason=f"账户重置: {old_balance} → {initial} USDT",
        lesson=f"Full account reset to {initial} USDT",
    )
    db.add(journal_entry)
    
    await db.commit()
    await db.refresh(wallet)
    
    logger.info(f"[Wallet] User {user_id} account fully reset to {initial} USDT")
    return wallet
