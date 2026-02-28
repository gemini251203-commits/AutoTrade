"""
Hub Log Model
==============
Agent Hub 操作日志模型

表: hub_logs — 记录 AI 智能体的每一次操作（值班巡逻、工具调用、分析决策等）
像交易员的工作日记，可按时间查询回溯。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class HubLog(Base):
    __tablename__ = "hub_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, default="System")
    
    # 日志类型: system / tool_call / ai_text / error / trade
    log_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    
    # 日志内容 (AI 说的话、工具名、错误信息等)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    
    __table_args__ = (
        Index("idx_hub_logs_user_time", "user_id", "created_at"),
        Index("idx_hub_logs_agent", "agent_id"),
    )
    
    def __repr__(self) -> str:
        return f"<HubLog #{self.id} [{self.log_type}] {self.agent_name}>"
