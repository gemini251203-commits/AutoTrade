"""
User AI Configuration Model
============================
每用户独立的 AI 配置

存储用户的 AI Provider 配置，API Key 等信息
API Key 使用 Fernet 对称加密存储
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AIProvider(str, Enum):
    """AI 提供商"""
    OLLAMA = "ollama"        # 本地 Ollama
    DEEPSEEK = "deepseek"    # DeepSeek API
    OPENAI = "openai"        # OpenAI API


class UserAIConfig(Base):
    """
    用户 AI 配置模型
    
    每个用户可以配置自己的 AI 提供商和 API Key
    API Key 加密存储，保证安全性
    """
    
    __tablename__ = "user_ai_configs"
    
    # ============================================
    # 主键和外键
    # ============================================
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,  # 每个用户只有一条配置
        index=True,
    )
    
    # ============================================
    # AI 提供商配置
    # ============================================
    
    provider: Mapped[AIProvider] = mapped_column(
        SQLEnum(AIProvider),
        default=AIProvider.OLLAMA,
        comment="AI 提供商: ollama/deepseek/openai",
    )
    
    # ============================================
    # Cloud API 配置 (DeepSeek / OpenAI)
    # ============================================
    
    api_base_url: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default="https://api.deepseek.com",
        comment="API Base URL",
    )
    
    api_key_encrypted: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="加密后的 API Key",
    )
    
    api_model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default="deepseek-chat",
        comment="模型名称",
    )
    
    # ============================================
    # Local LLM 配置 (Ollama)
    # ============================================
    
    ollama_base_url: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default="http://localhost:11434",
        comment="Ollama Base URL",
    )
    
    ollama_model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default="deepseek-r1:14b",
        comment="Ollama 模型名称",
    )
    
    # ============================================
    # 系统提示词
    # ============================================
    
    system_prompt: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default="You are QuantaPro, a professional Crypto Quant Trader.",
        comment="系统提示词",
    )
    
    # ============================================
    # 深度思考模式 (R1 + Chat 两阶段)
    # ============================================
    
    use_deep_thinking: Mapped[bool] = mapped_column(
        default=False,
        server_default="0",
        comment="启用深度思考: R1推理 → Chat执行",
    )
    
    # ============================================
    # 风险控制参数
    # ============================================
    
    max_leverage: Mapped[int] = mapped_column(
        Integer,
        default=20,
        comment="最大允许杠杆",
    )
    
    max_position_percent: Mapped[float] = mapped_column(
        Float,
        default=50.0,
        comment="最大仓位占比 (%)",
    )
    
    max_loss_percent: Mapped[float] = mapped_column(
        Float,
        default=5.0,
        comment="单笔最大亏损占比 (%)",
    )
    
    # ============================================
    # 时间戳
    # ============================================
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    
    # ============================================
    # 关联
    # ============================================
    
    user: Mapped["User"] = relationship("User", back_populates="ai_config")
    
    def __repr__(self) -> str:
        return f"<UserAIConfig(user_id={self.user_id}, provider={self.provider.value})>"
