"""
User Model
===========
用户账户模型
"""

from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.time_utils import utc_now


class User(Base):
    """用户模型"""
    
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
    
    # 关联
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="user", lazy="selectin"
    )
    tasks: Mapped[list["TaskTicket"]] = relationship(
        "TaskTicket", back_populates="user", lazy="selectin"
    )
    positions: Mapped[list["Position"]] = relationship(
        "Position", back_populates="user", lazy="selectin"
    )
    ai_config: Mapped["UserAIConfig"] = relationship(
        "UserAIConfig", back_populates="user", uselist=False, lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"

