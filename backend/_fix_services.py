"""
Batch fix: Replace datetime.now(timezone.utc) with utc_now() 
in all Python files that assign to SQLAlchemy model fields.

For files that only use datetime.now(timezone.utc) for .isoformat() or 
timestamp calculations (not DB writes), we keep them as-is.
"""
import os
import re

# Files where datetime.now(timezone.utc) is used for DB model field assignments
# These MUST use utc_now() because the DB columns are TIMESTAMP WITHOUT TIME ZONE
DB_WRITE_FILES = [
    # Services that write to models
    r"d:\AutoTrade\backend\app\services\trading\position_manager.py",
    r"d:\AutoTrade\backend\app\services\trading\order_executor.py",
    r"d:\AutoTrade\backend\app\services\trading\conditional_order.py",
    r"d:\AutoTrade\backend\app\services\market_collector.py",
    r"d:\AutoTrade\backend\app\services\news\monitor.py",
    r"d:\AutoTrade\backend\app\services\news\crawler.py",
    r"d:\AutoTrade\backend\app\services\grid\strategy.py",
    r"d:\AutoTrade\backend\app\services\quant\trend_scheduler.py",
    r"d:\AutoTrade\backend\app\services\task\executor.py",
    r"d:\AutoTrade\backend\app\services\agent\tools.py",
    r"d:\AutoTrade\backend\app\api\trend.py",
    # data_engine
    r"d:\AutoTrade\data_engine\binance_spider.py",
]

fixed = []
for fpath in DB_WRITE_FILES:
    if not os.path.exists(fpath):
        print(f"  SKIP (not found): {fpath}")
        continue
    
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "datetime.now(timezone.utc)" not in content:
        continue
    
    original = content
    
    # Add import if needed
    if "from app.core.time_utils import utc_now" not in content:
        lines = content.split("\n")
        last_import = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("from ") or line.strip().startswith("import "):
                last_import = i
        lines.insert(last_import + 1, "from app.core.time_utils import utc_now")
        content = "\n".join(lines)
    
    # Replace datetime.now(timezone.utc) with utc_now() 
    # BUT preserve cases where it's used for .isoformat() or .timestamp() or .strftime()
    # Those are fine since they don't write to DB columns
    
    # Strategy: replace ALL, then manually handle the non-DB cases
    count = content.count("datetime.now(timezone.utc)")
    content = content.replace("datetime.now(timezone.utc)", "utc_now()")
    
    if content != original:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        fixed.append((os.path.basename(fpath), count))

print(f"\nFixed {len(fixed)} files:")
for fname, count in fixed:
    print(f"  {fname}: {count} replacements")
