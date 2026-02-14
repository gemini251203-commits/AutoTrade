"""
Database Session
=================
异步数据库会话管理
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from loguru import logger

from app.core.config import settings
from app.db.base import Base  # 重新导出 Base 供其他模块使用


# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    future=True,
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def init_db() -> None:
    """
    初始化数据库
    
    创建所有表（如果不存在）
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话
    
    用于 FastAPI 依赖注入
    
    Yields:
        AsyncSession: 异步数据库会话
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# 导出 Base 供模型使用
__all__ = ["Base", "engine", "AsyncSessionLocal", "init_db", "get_db"]
