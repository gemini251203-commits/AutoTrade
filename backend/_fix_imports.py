"""
Fix misplaced 'from app.core.time_utils import utc_now' imports.

The previous batch script inserted the import after the LAST 'from/import' 
line in each file, which could be an inline import inside a method body.

This script:
1. Removes ALL misplaced 'from app.core.time_utils import utc_now' lines
2. Inserts it once at the top of the file (after the last module-level import)
"""
import os
import re

TARGET_IMPORT = "from app.core.time_utils import utc_now"

# All backend files that use utc_now()
FILES = [
    r"d:\AutoTrade\backend\app\services\trading\position_manager.py",
    r"d:\AutoTrade\backend\app\services\trading\order_executor.py",
    r"d:\AutoTrade\backend\app\services\trading\conditional_order.py",
    r"d:\AutoTrade\backend\app\services\market_collector.py",
    r"d:\AutoTrade\backend\app\services\news\monitor.py",
    r"d:\AutoTrade\backend\app\services\news\crawler.py",
    r"d:\AutoTrade\backend\app\services\grid\strategy.py",
    r"d:\AutoTrade\backend\app\services\quant\trend_scheduler.py",
    r"d:\AutoTrade\backend\app\services\quant\strategy.py",
    r"d:\AutoTrade\backend\app\services\task\executor.py",
    r"d:\AutoTrade\backend\app\services\agent\tools.py",
    r"d:\AutoTrade\backend\app\api\trend.py",
]

for fpath in FILES:
    if not os.path.exists(fpath):
        print(f"  SKIP: {fpath}")
        continue
    
    with open(fpath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Step 1: Remove ALL occurrences of the import (misplaced or correct)
    cleaned = []
    removed_count = 0
    for line in lines:
        if line.strip() == TARGET_IMPORT:
            removed_count += 1
            continue
        cleaned.append(line)
    
    # Step 2: Find the proper insertion point - after the last TOP-LEVEL import
    # Top-level imports are at indentation level 0, not inside functions/classes
    insert_idx = 0
    in_docstring = False
    for i, line in enumerate(cleaned):
        stripped = line.strip()
        
        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue
        
        # Track docstrings
        if '"""' in stripped or "'''" in stripped:
            count = stripped.count('"""') + stripped.count("'''")
            if count == 1:
                in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
            
        # Check if this is a top-level import (no leading whitespace)
        if not line[0].isspace() and (stripped.startswith("from ") or stripped.startswith("import ")):
            insert_idx = i + 1
        
        # Stop when we hit the first non-import, non-comment, non-empty line at top level
        # that isn't an import
        if not line[0].isspace() and not stripped.startswith("from ") and not stripped.startswith("import ") and not stripped.startswith("#") and not stripped.startswith('"') and not stripped.startswith("'"):
            break
    
    # Step 3: Check if utc_now() is actually used in this file
    file_content = "".join(cleaned)
    if "utc_now()" not in file_content:
        if removed_count > 0:
            # Was imported but not used - just remove it
            with open(fpath, "w", encoding="utf-8") as f:
                f.writelines(cleaned)
            print(f"  {os.path.basename(fpath)}: removed {removed_count} unused import(s)")
        continue
    
    # Step 4: Insert at the correct position
    cleaned.insert(insert_idx, TARGET_IMPORT + "\n")
    
    with open(fpath, "w", encoding="utf-8") as f:
        f.writelines(cleaned)
    
    print(f"  {os.path.basename(fpath)}: fixed (removed {removed_count}, inserted at line {insert_idx+1})")

print("\nDone!")
