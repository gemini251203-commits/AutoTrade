"""
Time Utilities
==============
统一时间格式化工具，确保所有返回前端的时间字符串带有 "Z" 后缀。
后端存储 UTC (datetime.now(timezone.utc))，.isoformat() 带时区信息，
前端 JS new Date("2026-02-24T18:45:00") 会误解为本地时间。
加 "Z" 后变成 "2026-02-24T18:45:00Z"，JS 正确解析为 UTC。
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """
    返回当前 UTC 时间 (无时区信息)。
    
    用于 SQLAlchemy 模型 default/onupdate，兼容
    PostgreSQL `TIMESTAMP WITHOUT TIME ZONE` 列。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    将 datetime 对象转为 ISO 格式字符串，末尾带 Z。
    
    例: datetime(2026, 2, 24, 18, 45) → "2026-02-24T18:45:00Z"
    """
    if dt is None:
        return None
    return dt.isoformat() + "Z"
