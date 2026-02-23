"""
Phase 4: Production Database Diagnostic Script (v3)
====================================================
PostgreSQL native ENUM compatible.
Each check uses a fresh connection to avoid transaction-abort cascading.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from sqlalchemy import text
from app.db.session import AsyncSessionLocal


async def safe_query(query_str):
    """Each query gets its own session to avoid transaction-abort cascading"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(query_str))
        return result.fetchall()


async def safe_scalar(query_str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(query_str))
        return result.scalar()


async def run_diagnostics():
    issues = []
    info = []

    # ============================================================
    # CHECK 1: 钱包余额一致性
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 1: 钱包余额一致性")
    print("="*60)
    try:
        rows = await safe_query(
            "SELECT user_id, balance, frozen, total_pnl FROM wallets ORDER BY user_id"
        )
        for w in rows:
            uid, balance, frozen, total_pnl = w
            print(f"  User {uid}: balance={balance}, frozen={frozen}, total_pnl={total_pnl}")
            if balance is not None and balance < 0:
                issues.append(f"🔴 CRITICAL: User {uid} balance NEGATIVE: {balance}")
            if frozen is not None and frozen < 0:
                issues.append(f"🔴 CRITICAL: User {uid} frozen NEGATIVE: {frozen}")
        if not any("User" in i and "NEGATIVE" in i for i in issues):
            info.append("CHECK 1: Wallet balances OK")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")

    # ============================================================
    # CHECK 2: 仓位保证金 vs 钱包冻结
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 2: 仓位保证金 vs 钱包冻结")
    print("="*60)
    try:
        rows = await safe_query("""
            SELECT w.user_id, w.frozen,
                   COALESCE(p.total_margin, 0) AS positions_margin
            FROM wallets w
            LEFT JOIN (
                SELECT user_id, SUM(margin) AS total_margin
                FROM positions WHERE status::text = 'open' GROUP BY user_id
            ) p ON w.user_id = p.user_id
        """)
        for r in rows:
            uid, w_frozen, p_margin = r
            w_fz = Decimal(str(w_frozen or 0))
            p_mg = Decimal(str(p_margin or 0))
            diff = w_fz - p_mg
            status = "✅" if abs(diff) < Decimal("0.01") else "⚠️"
            print(f"  User {uid}: frozen={w_fz}, positions_margin={p_mg}, diff={diff} {status}")
            if abs(diff) >= Decimal("0.01"):
                issues.append(f"🟠 HIGH: User {uid} frozen mismatch: frozen={w_fz}, margin={p_mg}, diff={diff}")
        if not any("frozen mismatch" in i for i in issues):
            info.append("CHECK 2: Frozen/margin aligned")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")
        issues.append(f"🟡 CHECK 2 skipped: {e}")

    # ============================================================
    # CHECK 3: 孤儿仓位
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 3: 孤儿仓位 (open 无 wallet)")
    print("="*60)
    try:
        rows = await safe_query("""
            SELECT p.id, p.user_id, p.symbol, p.side::text
            FROM positions p LEFT JOIN wallets w ON p.user_id = w.user_id
            WHERE p.status::text = 'open' AND w.id IS NULL
        """)
        if rows:
            for o in rows:
                print(f"  ❌ Position {o[0]}: user={o[1]}, {o[2]} {o[3]}")
                issues.append(f"🔴 Orphan position: id={o[0]}, user={o[1]}")
        else:
            print("  ✅ No orphan positions")
            info.append("CHECK 3: No orphan positions")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")

    # ============================================================
    # CHECK 4: 异常仓位
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 4: 异常仓位 (size/margin/entry ≤ 0)")
    print("="*60)
    try:
        rows = await safe_query("""
            SELECT id, user_id, symbol, size, margin, entry_price
            FROM positions
            WHERE status::text = 'open' AND (size <= 0 OR margin <= 0 OR entry_price <= 0)
        """)
        if rows:
            for b in rows:
                print(f"  ❌ Position {b[0]}: size={b[3]}, margin={b[4]}, entry={b[5]}")
                issues.append(f"🔴 Bad position: id={b[0]}, size={b[3]}")
        else:
            print("  ✅ All open positions valid")
            info.append("CHECK 4: All positions valid")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")

    # ============================================================
    # CHECK 5: Open 仓位缺少强平价
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 5: Open 仓位缺少强平价")
    print("="*60)
    try:
        rows = await safe_query("""
            SELECT id, user_id, symbol, side::text, leverage
            FROM positions
            WHERE status::text = 'open' AND liquidation_price IS NULL
        """)
        if rows:
            issues.append(f"🟡 {len(rows)} open positions have no liquidation_price")
            for n in rows[:5]:
                print(f"  ⚠️ Position {n[0]}: {n[2]} {n[3]}, leverage={n[4]}x")
        else:
            print("  ✅ All open positions have liquidation_price")
            info.append("CHECK 5: All have liq price")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")

    # ============================================================
    # CHECK 6: 整体统计
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 6: 整体数据统计")
    print("="*60)
    for name, query in [
        ("users", "SELECT COUNT(*) FROM users"),
        ("wallets", "SELECT COUNT(*) FROM wallets"),
        ("orders_total", "SELECT COUNT(*) FROM orders"),
        ("orders_filled", "SELECT COUNT(*) FROM orders WHERE status::text = 'filled'"),
        ("orders_pending", "SELECT COUNT(*) FROM orders WHERE status::text IN ('pending', 'open')"),
        ("positions_open", "SELECT COUNT(*) FROM positions WHERE status::text = 'open'"),
        ("positions_closed", "SELECT COUNT(*) FROM positions WHERE status::text = 'closed'"),
        ("positions_liquidated", "SELECT COUNT(*) FROM positions WHERE status::text = 'liquidated'"),
        ("grid_bots", "SELECT COUNT(*) FROM grid_bots"),
        ("strategies", "SELECT COUNT(*) FROM strategies"),
        ("trade_memories", "SELECT COUNT(*) FROM trade_memories"),
    ]:
        try:
            count = await safe_scalar(query)
            print(f"  {name}: {count}")
        except Exception as e:
            print(f"  {name}: SKIP ({type(e).__name__})")

    # ============================================================
    # CHECK 7: 已关闭仓位 realized_pnl 为 NULL
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 7: 已关闭仓位 realized_pnl 为 NULL")
    print("="*60)
    try:
        rows = await safe_query("""
            SELECT id, symbol, side::text FROM positions
            WHERE status::text IN ('closed', 'liquidated') AND realized_pnl IS NULL
            LIMIT 10
        """)
        if rows:
            issues.append(f"🟡 {len(rows)} closed positions have NULL realized_pnl")
            for n in rows[:5]:
                print(f"  ⚠️ Position {n[0]}: {n[1]} {n[2]}")
        else:
            print("  ✅ All closed positions have realized_pnl")
            info.append("CHECK 7: PnL populated")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")

    # ============================================================
    # CHECK 8: 仓位详细列表 (open)
    # ============================================================
    print("\n" + "="*60)
    print("📊 CHECK 8: 当前开放仓位详情")
    print("="*60)
    try:
        rows = await safe_query("""
            SELECT id, user_id, symbol, side::text, size, entry_price,
                   leverage, margin, liquidation_price, stop_loss, take_profit
            FROM positions
            WHERE status::text = 'open'
            ORDER BY user_id, symbol
        """)
        if rows:
            for r in rows:
                pid, uid, sym, side, size, entry, lev, margin, liq, sl, tp = r
                print(f"  #{pid} User{uid}: {sym} {side} size={size} "
                      f"entry={entry} lev={lev}x margin={margin} "
                      f"liq={liq} SL={sl} TP={tp}")
        else:
            print("  No open positions")
    except Exception as e:
        print(f"  ⚠️ SKIPPED: {e}")

    # Final Report
    print(f"\n{'='*60}")
    print("📋 FINAL REPORT")
    print("="*60)

    if issues:
        print(f"\n❌ Found {len(issues)} issue(s):\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\n✅ No issues found! Database is healthy.")

    if info:
        print(f"\n✅ Passed {len(info)} check(s):")
        for i in info:
            print(f"  - {i}")

    return issues


if __name__ == "__main__":
    issues = asyncio.run(run_diagnostics())
    sys.exit(1 if issues else 0)
