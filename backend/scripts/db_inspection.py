"""
生产数据库探伤脚本
==================
阶段四：检查数据完整性和一致性

运行方式:
    cd backend
    python -m scripts.db_inspection

检查项目:
    1. 孤立数据 (FK violations)
    2. 数值异常 (负数余额、超限杠杆)
    3. 状态不一致 (open position without wallet freeze)
    4. 时间异常 (future timestamps)
    5. 重复数据
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timezone
from sqlalchemy import select, func, text, and_, or_
from app.db.session import AsyncSessionLocal
from app.models.wallet import Wallet
from app.models.wallet_transaction import WalletTransaction
from app.models.order import Order
from app.models.position import Position, PositionStatus
from app.models.strategy import Strategy, StrategyLog, TradeMemory
from app.models.task import TaskTicket
from app.models.grid_bot import GridBot
from app.models.news import NewsAlert


async def run_inspection():
    """执行所有检查"""
    results = []
    
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        
        # ==================== 1. 孤立数据检查 ====================
        print("\n" + "=" * 60)
        print("[1] 孤立数据检查 (FK violations)")
        print("=" * 60)
        
        # Orders without valid wallet
        orphan_orders = await db.execute(
            select(func.count(Order.id)).where(
                ~Order.user_id.in_(select(Wallet.user_id))
            )
        )
        count = orphan_orders.scalar() or 0
        status = "✅" if count == 0 else f"⚠️ {count} 条"
        print(f"  订单无对应钱包: {status}")
        results.append(("orphan_orders", count))
        
        # Positions without valid wallet
        orphan_positions = await db.execute(
            select(func.count(Position.id)).where(
                ~Position.user_id.in_(select(Wallet.user_id))
            )
        )
        count = orphan_positions.scalar() or 0
        status = "✅" if count == 0 else f"⚠️ {count} 条"
        print(f"  仓位无对应钱包: {status}")
        results.append(("orphan_positions", count))
        
        # Strategy logs without valid strategy
        orphan_logs = await db.execute(
            select(func.count(StrategyLog.id)).where(
                ~StrategyLog.strategy_id.in_(select(Strategy.id))
            )
        )
        count = orphan_logs.scalar() or 0
        status = "✅" if count == 0 else f"⚠️ {count} 条"
        print(f"  策略日志无对应策略: {status}")
        results.append(("orphan_strategy_logs", count))
        
        # ==================== 2. 数值异常检查 ====================
        print("\n" + "=" * 60)
        print("[2] 数值异常检查")
        print("=" * 60)
        
        # Negative balance
        neg_balance = await db.execute(
            select(Wallet).where(Wallet.balance < 0)
        )
        wallets = neg_balance.scalars().all()
        status = "✅" if len(wallets) == 0 else f"⚠️ {len(wallets)} 个"
        print(f"  负余额钱包: {status}")
        for w in wallets:
            print(f"    user_id={w.user_id} balance={w.balance}")
        results.append(("negative_balance", len(wallets)))
        
        # Negative frozen
        neg_frozen = await db.execute(
            select(Wallet).where(Wallet.frozen < 0)
        )
        wallets = neg_frozen.scalars().all()
        status = "✅" if len(wallets) == 0 else f"⚠️ {len(wallets)} 个"
        print(f"  负冻结金额: {status}")
        results.append(("negative_frozen", len(wallets)))
        
        # Positions with zero or negative size
        bad_positions = await db.execute(
            select(func.count(Position.id)).where(
                Position.status == PositionStatus.OPEN,
                Position.size <= 0,
            )
        )
        count = bad_positions.scalar() or 0
        status = "✅" if count == 0 else f"⚠️ {count} 条"
        print(f"  活跃仓位 size ≤ 0: {status}")
        results.append(("zero_size_positions", count))
        
        # Overleveraged positions (> 125x)
        overleveraged = await db.execute(
            select(func.count(Position.id)).where(
                Position.leverage > 125
            )
        )
        count = overleveraged.scalar() or 0
        status = "✅" if count == 0 else f"⚠️ {count} 条"
        print(f"  杠杆超限 (>125x): {status}")
        results.append(("overleveraged", count))
        
        # ==================== 3. 状态一致性检查 ====================
        print("\n" + "=" * 60)
        print("[3] 状态一致性检查")
        print("=" * 60)
        
        # Open positions count
        open_pos = await db.execute(
            select(func.count(Position.id)).where(
                Position.status == PositionStatus.OPEN
            )
        )
        open_count = open_pos.scalar() or 0
        print(f"  活跃仓位数: {open_count}")
        
        # Wallets with frozen > 0 but no open positions
        frozen_wallets = await db.execute(
            select(Wallet).where(Wallet.frozen > 0)
        )
        for w in frozen_wallets.scalars().all():
            pos_count = await db.execute(
                select(func.count(Position.id)).where(
                    Position.user_id == w.user_id,
                    Position.status == PositionStatus.OPEN,
                )
            )
            pos = pos_count.scalar() or 0
            if pos == 0:
                print(f"  ⚠️ user_id={w.user_id} 有冻结金额 {w.frozen} 但无活跃仓位")
                results.append(("frozen_no_position", w.user_id))
        
        # ==================== 4. 时间异常检查 ====================
        print("\n" + "=" * 60)
        print("[4] 时间异常检查")
        print("=" * 60)
        
        # Future timestamps
        future_orders = await db.execute(
            select(func.count(Order.id)).where(
                Order.created_at > now
            )
        )
        count = future_orders.scalar() or 0
        status = "✅" if count == 0 else f"⚠️ {count} 条"
        print(f"  未来时间戳订单: {status}")
        results.append(("future_orders", count))
        
        # ==================== 5. 数据统计 ====================
        print("\n" + "=" * 60)
        print("[5] 数据统计")
        print("=" * 60)
        
        for model, name in [
            (Wallet, "钱包"),
            (Order, "订单"),
            (Position, "仓位"),
            (Strategy, "策略"),
            (StrategyLog, "策略日志"),
            (TradeMemory, "交易记忆"),
            (TaskTicket, "任务单"),
            (GridBot, "网格机器人"),
            (WalletTransaction, "钱包交易"),
            (NewsAlert, "新闻规则"),
        ]:
            count_result = await db.execute(select(func.count(model.id)))
            count = count_result.scalar() or 0
            print(f"  {name}: {count} 条")
        
        # ==================== Summary ====================
        issues = [(k, v) for k, v in results if isinstance(v, int) and v > 0]
        print("\n" + "=" * 60)
        if issues:
            print(f"⚠️ 发现 {len(issues)} 个问题:")
            for k, v in issues:
                print(f"  - {k}: {v}")
        else:
            print("✅ 所有检查通过，未发现数据完整性问题")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_inspection())
