"""
Multi-Tenant Wallet Isolation Test
====================================
验证多租户钱包隔离 - Alice 的操作不会影响 Bob

测试场景:
1. 初始化 Alice (user_id=1) -> 余额 10000
2. 初始化 Bob (user_id=2) -> 余额 10000
3. Alice 冻结 1000U
4. 断言: Alice 余额 = 9000, Bob 余额 = 10000 (关键!)

运行: python test_wallet.py
"""

import os
import sys
import asyncio
from decimal import Decimal
from pathlib import Path

# 设置测试环境
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["TRADING_MODE"] = "simulation"
os.environ["SIMULATION_INITIAL_BALANCE"] = "10000"

from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path, override=False)

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base import Base
from app.models.wallet import Wallet
from app.services.wallet_manager import WalletManager, InsufficientFundsError


# 用户 ID 常量
ALICE_ID = 1
BOB_ID = 2


async def run_isolation_test():
    """运行多租户隔离测试"""
    print("\n" + "=" * 60)
    print("Multi-Tenant Wallet Isolation Test")
    print("=" * 60)
    
    # 创建内存数据库
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] Database created")
    
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # ============================================
    # Test 1: 初始化 Alice
    # ============================================
    print("\n" + "-" * 60)
    print("Test 1: Initialize Alice (user_id=1)")
    print("-" * 60)
    
    async with Session() as db:
        async with db.begin():
            alice_wallet = await WalletManager.initialize_wallet(db, user_id=ALICE_ID)
            assert alice_wallet.balance == Decimal("10000"), \
                f"Alice should have 10000, got {alice_wallet.balance}"
            print(f"[PASS] Alice initialized: balance={alice_wallet.balance}")
    
    # ============================================
    # Test 2: 初始化 Bob
    # ============================================
    print("\n" + "-" * 60)
    print("Test 2: Initialize Bob (user_id=2)")
    print("-" * 60)
    
    async with Session() as db:
        async with db.begin():
            bob_wallet = await WalletManager.initialize_wallet(db, user_id=BOB_ID)
            assert bob_wallet.balance == Decimal("10000"), \
                f"Bob should have 10000, got {bob_wallet.balance}"
            print(f"[PASS] Bob initialized: balance={bob_wallet.balance}")
    
    # ============================================
    # Test 3: Alice 冻结 1000U
    # ============================================
    print("\n" + "-" * 60)
    print("Test 3: Alice freezes 1000 USDT")
    print("-" * 60)
    
    async with Session() as db:
        async with db.begin():
            alice_wallet = await WalletManager.freeze_funds(
                db, 
                user_id=ALICE_ID,  # <-- 显式指定 user_id
                amount=Decimal("1000")
            )
            assert alice_wallet.balance == Decimal("9000"), \
                f"Alice should have 9000, got {alice_wallet.balance}"
            assert alice_wallet.frozen == Decimal("1000"), \
                f"Alice should have 1000 frozen, got {alice_wallet.frozen}"
            print(f"[PASS] Alice after freeze: balance={alice_wallet.balance}, frozen={alice_wallet.frozen}")
    
    # ============================================
    # Test 4: 验证 Bob 不受影响 (关键!)
    # ============================================
    print("\n" + "-" * 60)
    print("Test 4: Verify Bob is NOT affected (CRITICAL)")
    print("-" * 60)
    
    async with Session() as db:
        bob_info = await WalletManager.get_balance(db, user_id=BOB_ID)
        
        # 关键断言: Bob 的余额必须仍然是 10000
        assert bob_info["balance"] == Decimal("10000"), \
            f"[SECURITY BREACH] Bob's balance changed! Expected 10000, got {bob_info['balance']}"
        assert bob_info["frozen"] == Decimal("0"), \
            f"[SECURITY BREACH] Bob has frozen funds! Expected 0, got {bob_info['frozen']}"
        
        print(f"[PASS] Bob's balance: {bob_info['balance']} (unchanged!)")
        print(f"[PASS] Bob's frozen: {bob_info['frozen']} (unchanged!)")
    
    # ============================================
    # Test 5: 最终状态对比
    # ============================================
    print("\n" + "-" * 60)
    print("Test 5: Final State Comparison")
    print("-" * 60)
    
    async with Session() as db:
        alice = await WalletManager.get_balance(db, user_id=ALICE_ID)
        bob = await WalletManager.get_balance(db, user_id=BOB_ID)
        
        print(f"  Alice: balance={alice['balance']}, frozen={alice['frozen']}")
        print(f"  Bob:   balance={bob['balance']}, frozen={bob['frozen']}")
        
        # 最终断言
        assert alice["balance"] == Decimal("9000")
        assert alice["frozen"] == Decimal("1000")
        assert bob["balance"] == Decimal("10000")
        assert bob["frozen"] == Decimal("0")
    
    # ============================================
    # 结果汇总
    # ============================================
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED - Multi-Tenant Isolation Verified")
    print("=" * 60)
    print("  [x] Alice initialized with 10000 USDT")
    print("  [x] Bob initialized with 10000 USDT")
    print("  [x] Alice froze 1000 USDT -> balance=9000")
    print("  [x] Bob's wallet UNCHANGED -> balance=10000")
    print("=" * 60)
    print("\n  ** SECURITY: User A cannot affect User B's wallet **\n")
    
    await engine.dispose()
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(run_isolation_test())
        sys.exit(0 if success else 1)
    except AssertionError as e:
        print(f"\n[SECURITY FAILURE] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
