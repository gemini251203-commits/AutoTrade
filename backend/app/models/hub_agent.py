"""
Hub Agent Model
================
Agent Hub 智能体中枢数据模型

表: hub_agents — 存储用户创建的 AI 智能体配置与运行状态
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, Boolean,
    ForeignKey, Index, Enum as SQLEnum, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


# ============================================================
# 枚举
# ============================================================

class HubAgentStatus(str, Enum):
    """智能体运行状态"""
    IDLE   = "idle"       # 已创建，未运行
    ACTIVE = "active"     # 正在运行
    PAUSED = "paused"     # 暂停
    ERROR  = "error"      # 出错


# ============================================================
# ORM 模型
# ============================================================

class HubAgent(Base):
    """
    Hub 智能体
    
    每个用户可创建多个智能体，独立配置 AI 模型、提示词和角色。
    独裁者模式: 单个 active 智能体接管系统
    董事会模式: 多个 active 智能体辩论决策
    """
    __tablename__ = "hub_agents"
    
    # === 主键 ===
    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    
    # === 身份 ===
    name: Mapped[str] = mapped_column(
        String(100),
        comment="智能体名称, e.g. Alpha 猎手",
    )
    role: Mapped[str] = mapped_column(
        String(50),
        default="trader",
        comment="角色标签: trader / analyst / risk_advisor",
    )
    avatar: Mapped[str] = mapped_column(
        String(20),
        default="BOT",
        comment="Avatar identifier (first letter or code)",
    )
    
    # === AI 配置 ===
    provider: Mapped[str] = mapped_column(
        String(20),
        default="deepseek",
        comment="AI 供应商: deepseek / openai / ollama",
    )
    model: Mapped[str] = mapped_column(
        String(100),
        default="deepseek-chat",
        comment="模型名称",
    )
    api_base_url: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="API Base URL (覆盖全局配置)",
    )
    api_key_enc: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="加密后的 API Key (独立于全局)",
    )
    system_prompt: Mapped[str] = mapped_column(
        Text,
        default="",
        comment="系统提示词 (注入系统说明书 + 角色定制)",
    )
    temperature: Mapped[float] = mapped_column(
        Float,
        default=0.7,
        comment="AI 温度参数 0.0~2.0",
    )
    
    # === 运行状态 ===
    status: Mapped[HubAgentStatus] = mapped_column(
        SQLEnum(HubAgentStatus),
        default=HubAgentStatus.IDLE,
        comment="运行状态: idle / active / paused / error",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        comment="是否激活 (前端开关)",
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        comment="上次执行时间",
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="最近错误信息",
    )
    total_runs: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="累计执行次数",
    )
    total_trades: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="累计交易次数",
    )
    
    # === 轮询间隔 ===
    polling_interval: Mapped[int] = mapped_column(
        Integer,
        default=5,
        server_default="5",
        comment="轮询间隔(分钟): 1/5/15/60",
    )
    
    # === 工具权限 ===
    allowed_tools: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="授权工具列表 (JSON数组). null=全部, []=禁用, ['get_price','place_order']=指定",
    )
    
    # === 提示词模板关联 ===
    active_template_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        comment="当前使用的提示词模板 ID (null=使用 system_prompt 自由文本)",
    )
    
    # === 时间戳 ===
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
    )
    
    # === 索引 ===
    __table_args__ = (
        Index("ix_hub_agents_user_active", "user_id", "is_active"),
    )
    
    def __repr__(self) -> str:
        return f"<HubAgent #{self.id} '{self.name}' [{self.status.value}]>"
