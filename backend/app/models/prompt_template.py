"""
Prompt Template Model
======================
提示词模板数据模型

表: prompt_templates — 存储版本化的提示词模板
支持:
- 策略与风控规则分区存储
- 市况标签和资金级别标记
- 收益追踪 (关联 Position)
- 版本演化树 (parent_id)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, DateTime, Boolean,
    ForeignKey, Index, JSON, Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import utc_now


class PromptTemplate(Base):
    """
    提示词模板

    每个用户可创建多个模板版本，通过 active_template_id 关联到 HubAgent。
    交易时的 template_id 写入 Position，实现 "提示词 → 交易 → 盈亏" 追踪。
    """
    __tablename__ = "prompt_templates"

    # === 主键 ===
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # === 身份 ===
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="模板名称, e.g. '高频量化v3'",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        comment="版本号 (同名模板自增)",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="模板描述 (用户备注)",
    )

    # === 提示词内容 (分区存储) ===
    strategy_prompt: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
        comment="交易策略描述 (核心策略规则)",
    )
    risk_rules: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
        comment="风控规则 (红线/禁止行为)",
    )
    behavior_directives: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
        comment="行为指令 (回复风格/效率要求, 可选覆盖系统默认)",
    )

    # === 兼容自由文本模式 ===
    raw_prompt: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
        comment="原始自由文本提示词 (兼容模式, 非结构化)",
    )
    is_structured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
        comment="是否使用结构化模式 (True=分区, False=自由文本)",
    )

    # === 市况标签 ===
    market_tags: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment='适用市况标签 JSON: ["trending_up","sideways","small_fund"]',
    )

    # === 版本演化 ===
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("prompt_templates.id", ondelete="SET NULL"),
        nullable=True,
        comment="从哪个版本 fork/演化而来 (版本树)",
    )
    is_preset: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
        comment="是否为系统预置模板",
    )

    # === 收益追踪 (由后端定期聚合更新) ===
    total_trades: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="使用此模板产生的交易总数",
    )
    win_trades: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        comment="盈利交易数",
    )
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("0"),
        server_default="0",
        nullable=False,
        comment="使用此模板的总盈亏 USDT",
    )
    active_hours: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        server_default="0",
        nullable=False,
        comment="模板累计使用时长 (小时)",
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
        Index("ix_prompt_templates_user", "user_id"),
        Index("ix_prompt_templates_user_name", "user_id", "name"),
    )

    # === 计算属性 ===
    @property
    def win_rate(self) -> float:
        """胜率 (%)"""
        if self.total_trades == 0:
            return 0.0
        return round(self.win_trades / self.total_trades * 100, 1)

    @property
    def effective_prompt(self) -> str:
        """获取有效提示词内容 (兼容两种模式)"""
        if not self.is_structured:
            return self.raw_prompt
        # 结构化模式: 组装
        parts = []
        if self.strategy_prompt:
            parts.append(self.strategy_prompt)
        if self.risk_rules:
            parts.append(f"\n{self.risk_rules}")
        if self.behavior_directives:
            parts.append(f"\n{self.behavior_directives}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return (
            f"<PromptTemplate #{self.id} '{self.name}' v{self.version} "
            f"trades={self.total_trades} pnl={self.total_pnl}>"
        )
