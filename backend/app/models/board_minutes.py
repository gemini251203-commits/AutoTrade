"""
Board Minutes Model
====================
董事会纪要模型

表: board_minutes — 存储每日自动生成的《董事会纪要》
由 MemoryConsolidator 坍缩引擎自动生成。

每份纪要包含：
- 当日交易总结 (盈亏)
- 各 AI 观点与决策记录
- 核心教训提炼
- 重要性评分
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, Date,
    ForeignKey, Index, JSON, UniqueConstraint, Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class BoardMinutes(Base):
    """
    董事会纪要
    
    每人每天最多一份纪要（唯一约束: user_id + date）。
    被注入到所有 AI 的 System Prompt 作为「共享记忆」。
    """
    __tablename__ = "board_minutes"
    
    # === 主键 ===
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # === 纪要核心内容 ===
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="纪要所属日期",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="精炼总结 (~300字)",
    )
    key_lessons: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="核心教训 (1-2句)",
    )
    
    # === 元数据 ===
    importance: Mapped[int] = mapped_column(
        Integer,
        default=5,
        comment="重要性评分 1-10 (AI 自评)",
    )
    trade_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="当日交易笔数",
    )
    pnl_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("0"),
        comment="当日总盈亏 USDT",
    )
    agents_mentioned: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment='点名的AI名单 ["Deepseek", "Alpha猎手"]',
    )
    
    # === 时间戳 ===
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )
    
    # === 约束与索引 ===
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_board_minutes_user_date"),
        Index("ix_board_minutes_user_date", "user_id", "date"),
    )
    
    def __repr__(self) -> str:
        return f"<BoardMinutes user={self.user_id} date={self.date} importance={self.importance}>"
