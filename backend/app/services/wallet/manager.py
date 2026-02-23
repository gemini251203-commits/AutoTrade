"""
Wallet Manager Service (Multi-Tenant)
======================================
资金管理服务 - 严格的多租户数据隔离

⚠️ 安全铁律:
1. 所有方法必须将 user_id 作为第一个必填参数
2. 所有 SQL 查询必须带 WHERE user_id = :user_id
3. 事务中使用 FOR UPDATE 锁定用户行，防止并发冲突

核心方法:
- initialize_wallet(db, user_id): 为指定用户初始化钱包
- get_balance(db, user_id): 获取指定用户的余额
- freeze_funds(db, user_id, amount): 冻结指定用户的资金
- unfreeze_funds(db, user_id, amount): 解冻指定用户的资金
"""

import os
from decimal import Decimal
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.wallet import Wallet


# ============================================
# 加载配置
# ============================================

_env_path = Path(__file__).parent.parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

TRADING_MODE = os.getenv("TRADING_MODE", "simulation").lower()
INITIAL_BALANCE = Decimal(os.getenv("SIMULATION_INITIAL_BALANCE", "1000"))  # Default: 1000 USDT


# ============================================
# 自定义异常
# ============================================

class InsufficientFundsError(Exception):
    """
    余额不足异常
    
    当用户尝试冻结超过可用余额的资金时抛出。
    """
    def __init__(self, user_id: int, required: Decimal, available: Decimal):
        self.user_id = user_id
        self.required = required
        self.available = available
        super().__init__(
            f"User {user_id}: Insufficient funds - "
            f"required={required}, available={available}"
        )


class WalletNotFoundError(Exception):
    """钱包不存在异常"""
    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(f"Wallet not found for user_id={user_id}")


# ============================================
# 钱包管理器 (静态方法，所有操作都需要 user_id)
# ============================================

class WalletManager:
    """
    钱包管理器 - 多租户隔离版
    
    ⚠️ 安全设计:
    - 所有方法都是静态方法，必须传入 db session 和 user_id
    - 绝不会有"默认用户"的概念，彻底杜绝越权访问
    - SQL 查询强制包含 WHERE user_id = :user_id
    
    使用示例:
        async with db.begin():  # ACID 事务
            await WalletManager.initialize_wallet(db, user_id=alice_id)
            await WalletManager.freeze_funds(db, user_id=alice_id, amount=100)
    """
    
    # ============================================
    # 查询方法
    # ============================================
    
    @staticmethod
    async def get_wallet(
        db: AsyncSession, 
        user_id: int,
        *,
        for_update: bool = False,
    ) -> Optional[Wallet]:
        """
        获取指定用户的钱包
        
        Args:
            db: 数据库会话
            user_id: 用户 ID (必填!)
            for_update: 是否锁定行 (用于事务中的更新操作)
        
        Returns:
            Wallet 实例或 None
        
        SQL 等价于:
            SELECT * FROM wallets WHERE user_id = :user_id [FOR UPDATE]
        """
        query = select(Wallet).where(Wallet.user_id == user_id)
        
        if for_update:
            # FOR UPDATE: 在事务中锁定该行，防止并发修改
            query = query.with_for_update()
        
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_balance(db: AsyncSession, user_id: int) -> dict:
        """
        获取指定用户的余额信息
        
        Args:
            db: 数据库会话
            user_id: 用户 ID (必填!)
        
        Returns:
            {
                "user_id": int,
                "balance": Decimal,  # 可用余额
                "frozen": Decimal,   # 冻结金额
                "total_pnl": Decimal # 已实现盈亏
            }
        
        Raises:
            WalletNotFoundError: 钱包不存在
        """
        wallet = await WalletManager.get_wallet(db, user_id)
        
        if wallet is None:
            raise WalletNotFoundError(user_id)
        
        return {
            "user_id": wallet.user_id,
            "balance": wallet.balance,
            "frozen": wallet.frozen,
            "total_pnl": wallet.total_pnl,
        }
    
    # ============================================
    # 初始化方法
    # ============================================
    
    @staticmethod
    async def initialize_wallet(
        db: AsyncSession, 
        user_id: int,
    ) -> Wallet:
        """
        为指定用户初始化钱包
        
        规则:
        - 如果钱包已存在，直接返回
        - 如果是 simulation 模式，空投初始资金
        - 如果是 live 模式，初始余额为 0
        
        Args:
            db: 数据库会话
            user_id: 用户 ID (必填!)
        
        Returns:
            Wallet 实例
        
        ⚠️ ACID 保障:
        需要在事务中调用: async with db.begin():
        """
        # 检查是否已存在
        wallet = await WalletManager.get_wallet(db, user_id)
        
        if wallet is not None:
            logger.info(
                f"[WalletManager] Wallet exists for user {user_id}: "
                f"balance={wallet.balance}"
            )
            return wallet
        
        # 创建新钱包
        if TRADING_MODE == "simulation":
            initial_balance = INITIAL_BALANCE
            logger.info(
                f"[WalletManager] Creating SIMULATION wallet for user {user_id}, "
                f"airdrop: {initial_balance} USDT"
            )
        else:
            initial_balance = Decimal("0")
            logger.info(
                f"[WalletManager] Creating LIVE wallet for user {user_id}"
            )
        
        wallet = Wallet(
            user_id=user_id,
            balance=initial_balance,
            frozen=Decimal("0"),
            total_pnl=Decimal("0"),
        )
        
        db.add(wallet)
        await db.flush()
        
        return wallet
    get_or_create_wallet = initialize_wallet
    # ============================================
    # 资金操作方法 (需要事务保障)
    # ============================================
    
    @staticmethod
    async def freeze_funds(
        db: AsyncSession, 
        user_id: int,
        amount: Decimal,
    ) -> Wallet:
        """
        冻结指定用户的资金
        
        流程:
        1. 锁定该用户的钱包行 (FOR UPDATE)
        2. 检查可用余额是否充足
        3. balance -= amount, frozen += amount
        
        Args:
            db: 数据库会话
            user_id: 用户 ID (必填!)
            amount: 冻结金额
        
        Returns:
            更新后的 Wallet 实例
        
        Raises:
            InsufficientFundsError: 余额不足
            WalletNotFoundError: 钱包不存在
        
        ⚠️ ACID 保障:
        - 使用 FOR UPDATE 锁定用户行
        - 需要在事务中调用: async with db.begin():
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        # 使用 FOR UPDATE 锁定该用户的钱包行
        wallet = await WalletManager.get_wallet(db, user_id, for_update=True)
        
        if wallet is None:
            raise WalletNotFoundError(user_id)
        
        # 检查余额是否充足
        if wallet.balance < amount:
            raise InsufficientFundsError(
                user_id=user_id,
                required=amount,
                available=wallet.balance,
            )
        
        # 原子操作: 可用 -> 冻结
        old_balance = wallet.balance
        wallet.balance -= amount
        wallet.frozen += amount
        
        logger.info(
            f"[WalletManager] User {user_id}: Frozen {amount}, "
            f"balance {old_balance} -> {wallet.balance}"
        )
        
        return wallet
    
    @staticmethod
    async def unfreeze_funds(
        db: AsyncSession, 
        user_id: int,
        amount: Decimal,
    ) -> Wallet:
        """
        解冻指定用户的资金
        
        Args:
            db: 数据库会话
            user_id: 用户 ID (必填!)
            amount: 解冻金额
        
        Returns:
            更新后的 Wallet 实例
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        
        wallet = await WalletManager.get_wallet(db, user_id, for_update=True)
        
        if wallet is None:
            raise WalletNotFoundError(user_id)
        
        if wallet.frozen < amount:
            raise ValueError(
                f"User {user_id}: Cannot unfreeze {amount}, only {wallet.frozen} frozen"
            )
        
        # 原子操作: 冻结 -> 可用
        wallet.frozen -= amount
        wallet.balance += amount
        
        logger.info(
            f"[WalletManager] User {user_id}: Unfrozen {amount}, "
            f"balance -> {wallet.balance}"
        )
        
        return wallet
    
    @staticmethod
    async def settle_pnl(
        db: AsyncSession, 
        user_id: int,
        pnl: Decimal,
        frozen_release: Decimal,
    ) -> Wallet:
        """
        结算指定用户的盈亏
        
        Args:
            db: 数据库会话
            user_id: 用户 ID (必填!)
            pnl: 本次盈亏 (正=盈利, 负=亏损)
            frozen_release: 释放的冻结金额
        
        Returns:
            更新后的 Wallet 实例
        """
        wallet = await WalletManager.get_wallet(db, user_id, for_update=True)
        
        if wallet is None:
            raise WalletNotFoundError(user_id)
        
        # 🔥 防御性编程: 防止 frozen 下溢变负
        if frozen_release > wallet.frozen:
            logger.warning(
                f"[WalletManager] User {user_id}: frozen underflow! "
                f"frozen={wallet.frozen}, release={frozen_release}. Clamping to 0."
            )
            frozen_release = wallet.frozen

        wallet.frozen -= frozen_release
        wallet.balance += frozen_release + pnl
        wallet.total_pnl += pnl
        
        logger.info(
            f"[WalletManager] User {user_id}: Settled PnL {pnl}, "
            f"balance -> {wallet.balance}, total_pnl -> {wallet.total_pnl}"
        )
        
        return wallet

    @staticmethod
    async def deduct_fee(
        db: AsyncSession, 
        user_id: int,
        amount: Decimal,
    ) -> Wallet:
        """
        扣除交易手续费
        
        从可用余额中直接扣除 (币安规则: 手续费从余额扣)
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            amount: 手续费金额 (USDT)
        
        Returns:
            更新后的 Wallet 实例
        """
        if amount <= 0:
            return await WalletManager.get_wallet(db, user_id)
        
        wallet = await WalletManager.get_wallet(db, user_id, for_update=True)
        
        if wallet is None:
            raise WalletNotFoundError(user_id)
        
        # 🔥 防御性编程: 防止 balance 下溢变负
        if wallet.balance < amount:
            logger.warning(
                f"[WalletManager] User {user_id}: balance underflow! "
                f"balance={wallet.balance}, fee={amount}. Clamping to 0."
            )
            wallet.balance = Decimal("0")
        else:
            wallet.balance -= amount
        
        logger.info(
            f"[WalletManager] User {user_id}: Fee deducted {amount}, "
            f"balance -> {wallet.balance}"
        )
        
        return wallet

    # ============================================
    # 划转方法 (合约账户 ↔ 资金账户)
    # ============================================
    
    @staticmethod
    async def transfer_funds(
        db: AsyncSession, 
        user_id: int,
        amount: Decimal,
        direction: str,  # "to_funding" | "to_contract"
    ) -> Wallet:
        """
        账户间划转 (合约 ↔ 资金)
        
        规则:
        - to_funding: 合约 → 资金 (只能转可用余额, 冻结不可转)
        - to_contract: 资金 → 合约
        - 划转后需重算爆仓价
        
        Args:
            db: 数据库会话
            user_id: 用户 ID
            amount: 划转金额 (> 0)
            direction: "to_funding" 或 "to_contract"
        
        Returns:
            更新后的 Wallet 实例
        
        Raises:
            InsufficientFundsError: 来源账户余额不足
            ValueError: 无效参数
        """
        if amount <= 0:
            raise ValueError("划转金额必须大于 0")
        
        if direction not in ("to_funding", "to_contract"):
            raise ValueError(f"无效划转方向: {direction}")
        
        # 锁定钱包行
        wallet = await WalletManager.get_wallet(db, user_id, for_update=True)
        
        if wallet is None:
            raise WalletNotFoundError(user_id)
        
        if direction == "to_funding":
            # 合约 → 资金: 只能转可用余额
            if wallet.balance < amount:
                raise InsufficientFundsError(
                    user_id=user_id,
                    required=amount,
                    available=wallet.balance,
                )
            wallet.balance -= amount
            wallet.funding_balance += amount
            tx_type = "transfer_out"
            note = f"合约→资金 划转 {amount} USDT"
        else:
            # 资金 → 合约
            if wallet.funding_balance < amount:
                raise InsufficientFundsError(
                    user_id=user_id,
                    required=amount,
                    available=wallet.funding_balance,
                )
            wallet.funding_balance -= amount
            wallet.balance += amount
            tx_type = "transfer_in"
            note = f"资金→合约 划转 {amount} USDT"
        
        # 记录流水
        from app.models.wallet_transaction import WalletTransaction
        tx = WalletTransaction(
            user_id=user_id,
            type=tx_type,
            amount=amount if direction == "to_contract" else -amount,
            balance_after=wallet.balance,
            note=note,
        )
        db.add(tx)
        
        logger.info(
            f"[WalletManager] User {user_id}: Transfer {direction} {amount} USDT, "
            f"contract_balance={wallet.balance}, funding_balance={wallet.funding_balance}"
        )
        
        return wallet

