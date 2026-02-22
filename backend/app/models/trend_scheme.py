"""
Trend Scheme Models
====================
趋势分析方案 + 分析快照

表:
- trend_schemes: 趋势分析方案 (YAML 配置)
- trend_snapshots: 趋势分析结果快照
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, Boolean, DateTime,
    ForeignKey, Index, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrendScheme(Base):
    """
    趋势分析方案

    存储用户配置的 YAML 分析方案和运行状态
    """
    __tablename__ = "trend_schemes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(
        String(100),
        comment="方案名称",
    )
    config_yaml: Mapped[str] = mapped_column(
        Text,
        comment="YAML 分析方案配置",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="是否启用 (定时分析)",
    )
    is_preset: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否预置方案",
    )

    # 最新分析结果 (缓存)
    last_result: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="最近一次分析结果 JSON",
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="上次分析时间",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_trend_schemes_user_active", "user_id", "is_active"),
    )

    def __repr__(self):
        status = "🟢" if self.is_active else "⚪"
        return f"<TrendScheme {status} {self.name}>"


class TrendSnapshot(Base):
    """
    趋势分析快照

    记录每次分析的完整结果
    """
    __tablename__ = "trend_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("trend_schemes.id"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    symbol: Mapped[str] = mapped_column(
        String(20),
        index=True,
        comment="交易对",
    )

    # 分析结果
    direction: Mapped[str] = mapped_column(
        String(20),
        comment="趋势方向: uptrend/downtrend/ranging",
    )
    direction_score: Mapped[float] = mapped_column(
        Float,
        default=0,
    )
    strength: Mapped[str] = mapped_column(
        String(20),
        comment="趋势强度: strong/moderate/weak",
    )
    strength_score: Mapped[float] = mapped_column(
        Float,
        default=0,
    )
    volatility: Mapped[str] = mapped_column(
        String(20),
        comment="波动率: high/normal/low",
    )
    momentum: Mapped[str] = mapped_column(
        String(20),
        comment="动量: bullish/bearish/neutral",
    )
    regime: Mapped[str] = mapped_column(
        String(30),
        comment="市场体制: trending_up/trending_down/ranging/volatile",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        default=0,
    )

    # 建议
    suitable_strategies: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
    )

    # 完整结果
    result_json: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="完整 TrendResult JSON",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_trend_snapshots_scheme_time", "scheme_id", "created_at"),
    )
