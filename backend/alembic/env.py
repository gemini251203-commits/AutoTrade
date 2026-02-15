"""
Alembic Environment Configuration
==================================
配置 Alembic 迁移环境，使用 PostgreSQL
"""

import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from alembic import context

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入 Base 和所有模型
from app.db.base import Base
from app.models.user import User
from app.models.wallet import Wallet
from app.models.order import Order
from app.models.task import TaskTicket
from app.models.market import Kline
from app.models.strategy import Strategy, StrategyLog, TradeMemory

# Alembic 配置对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置 target_metadata 为我们的 Base.metadata
# 这样 Alembic autogenerate 才能识别我们的模型
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式迁移
    用于生成 SQL 脚本而不实际连接数据库
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式迁移
    直接连接数据库执行迁移
    """
    # 使用同步引擎 (Alembic 不支持 async)
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
