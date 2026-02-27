"""
Analysis Scratchpad — AI 分析记事本
=====================================
跨周期持久化 AI 的中间分析状态

解决问题:
    AI 每次唤醒都是"无状态"的，无法追踪:
    - 形态演变 (如 W 底的右肩是否完成)
    - 跨周期判断 (连续 3 次看空)
    - 自设关键价位 (支撑/阻力)

用法:
    每次 Autopilot 周期:
    1. 读取上次 scratchpad 注入 AI prompt
    2. AI 回复中用 [SCRATCHPAD]...[/SCRATCHPAD] 标记新结论
    3. 系统解析并持久化到数据库
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, JSON, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class AnalysisScratchpad(Base):
    """AI 分析记事本 — 跨周期持久化中间状态"""
    __tablename__ = "analysis_scratchpads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户 ID")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, comment="交易对")
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="autopilot",
        comment="来源: autopilot / ai_reviewer",
    )

    # 核心: AI 的分析结论 (自由文本)
    context: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
        comment="AI 上次的分析结论/观察/判断",
    )

    # 结构化扩展 (可选)
    key_levels: Mapped[dict] = mapped_column(
        JSON, nullable=True,
        comment='关键价位 {"support": [65000], "resistance": [70000]}',
    )
    pattern_tracking: Mapped[dict] = mapped_column(
        JSON, nullable=True,
        comment='形态追踪 {"type": "w_bottom", "stage": "right_shoulder"}',
    )

    # 统计
    cycle_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="已更新次数",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now,
        comment="最后更新时间",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now,
        comment="创建时间",
    )

    __table_args__ = (
        Index("ix_scratchpad_user_symbol", "user_id", "symbol", "source", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<Scratchpad(user={self.user_id}, {self.symbol}, "
            f"src={self.source}, cycles={self.cycle_count})>"
        )
