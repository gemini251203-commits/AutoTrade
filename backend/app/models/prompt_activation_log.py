"""
Prompt Activation Log Model
=============================
提示词激活日志

表: prompt_activation_logs — 记录每次 Agent 切换/激活提示词模板的历史
用于:
- 追踪某个时间段内使用了哪个模板
- 计算模板的累计使用时长
- 分析模板切换与收益的相关性
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer, DateTime, ForeignKey, Index, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class PromptActivationLog(Base):
    """
    提示词激活日志

    每次 Agent 切换模板时插入一条记录。
    deactivated_at 在下次切换时回填。
    """
    __tablename__ = "prompt_activation_logs"

    # === 主键 ===
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hub_agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("prompt_templates.id", ondelete="CASCADE"),
        nullable=False,
        comment="激活的提示词模板 ID",
    )

    # === 时间 ===
    activated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
        comment="激活时间",
    )
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="停用时间 (切换到其他模板时回填)",
    )

    # === 切换原因 ===
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="切换原因 (手动/市况推荐/自动)",
    )

    # === 索引 ===
    __table_args__ = (
        Index("ix_prompt_activation_user_agent", "user_id", "agent_id"),
        Index("ix_prompt_activation_template", "template_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PromptActivationLog agent={self.agent_id} "
            f"template={self.template_id} "
            f"at={self.activated_at}>"
        )
