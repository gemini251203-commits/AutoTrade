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
    """
    wallet = await WalletManager.get_wallet(db, current_user.id)
    
    if not wallet:
        # 钱包不存在，初始化
        wallet = await WalletManager.initialize_wallet(db, current_user.id)
        await db.commit()
        await db.refresh(wallet)
        logger.info(f"[Wallet] Auto-initialized wallet for user {current_user.id}: {wallet.balance} USDT")
    
    return WalletBalanceResponse(
        available=wallet.balance,
        frozen=wallet.frozen,
        total_equity=wallet.total_equity,
        total_pnl=wallet.total_pnl,
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
    
    # 5. 删除所有流水记录
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
