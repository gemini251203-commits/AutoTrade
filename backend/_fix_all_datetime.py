"""
全面修复：替换所有 datetime.now(timezone.utc) 为 utc_now()
- 写入DB模型字段的：替换为 utc_now()
- .isoformat()/.strftime()/.timestamp() 的：也替换为 utc_now()（都兼容）
- security.py 中用于JWT的：保持不动（JWT需要tz-aware）
"""
import os
import re

TARGET = "datetime.now(timezone.utc)"
REPLACEMENT = "utc_now()"
IMPORT_LINE = "from app.core.time_utils import utc_now"

BASE = r"d:\AutoTrade\backend\app"

# 所有需要修复的文件（排除 security.py 因为 JWT 需要 tz-aware，排除 time_utils.py 本身）
SKIP_FILES = {"time_utils.py", "security.py"}

def fix_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    if TARGET not in content:
        return 0
    
    basename = os.path.basename(filepath)
    if basename in SKIP_FILES:
        return 0
    
    original = content
    
    # 计算替换数
    count = content.count(TARGET)
    
    # 替换所有实例
    content = content.replace(TARGET, REPLACEMENT)
    
    # 确保有 import
    if IMPORT_LINE not in content:
        lines = content.split("\n")
        # 找到最后一个顶级 import (不在函数/类内部)
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not line[0:1].isspace() and (stripped.startswith("from ") or stripped.startswith("import ")):
                insert_idx = i + 1
        lines.insert(insert_idx, IMPORT_LINE)
        content = "\n".join(lines)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    return count

# 遍历所有 Python 文件
total_fixes = 0
fixed_files = []

for root, dirs, files in os.walk(BASE):
    # 跳过 __pycache__
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for fname in files:
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(root, fname)
        count = fix_file(fpath)
        if count > 0:
            rel = os.path.relpath(fpath, BASE)
            fixed_files.append((rel, count))
            total_fixes += count

print(f"\n修复完成! 共 {total_fixes} 处，涉及 {len(fixed_files)} 个文件:\n")
for rel, count in sorted(fixed_files):
    print(f"  {rel}: {count} 处")

# 验证
print(f"\n=== 验证残留 ===")
remaining = 0
for root, dirs, files in os.walk(BASE):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for fname in files:
        if not fname.endswith(".py") or fname in SKIP_FILES:
            continue
        fpath = os.path.join(root, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if TARGET in line:
                    remaining += 1
                    print(f"  残留: {os.path.relpath(fpath, BASE)}:{i}")

if remaining == 0:
    print("  ✅ 无残留！")
else:
    print(f"  ⚠️ 还有 {remaining} 处残留")
