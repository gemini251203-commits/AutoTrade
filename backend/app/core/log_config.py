"""
Log Configuration Module
==========================
统一日志配置

功能:
1. 文件持久化 — 日志存入 logs/ 目录
2. 自动轮转 — 按大小（10MB）或时间（每天）轮转
3. 错误单独存放 — error.log 只记录 WARNING+
4. JSON 格式 — 生产环境输出结构化 JSON（便于 ELK/Loki）
5. 控制台彩色输出 — 开发环境保持可读性

日志文件结构:
    logs/
    ├── app.log          # 全量日志 (DEBUG+)
    ├── error.log        # 错误日志 (WARNING+)
    └── access.log       # 访问日志 (INFO, 仅 [AccessLog] 标记的)

使用方式:
    from app.core.log_config import setup_logging
    setup_logging()  # 在 main.py 的 lifespan 最前面调用
"""

import sys
from pathlib import Path
from loguru import logger

from app.core.config import settings


# 日志目录
LOG_DIR = Path(__file__).parent.parent.parent / "logs"  # backend/logs/


def setup_logging():
    """
    配置 loguru 日志系统
    
    在应用启动时调用一次。
    """
    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # 移除默认 handler（避免重复）
    logger.remove()
    
    # ==================== 控制台输出 ====================
    # 开发环境: 彩色格式，DEBUG 级别
    # 生产环境: 简洁格式，INFO 级别
    
    if settings.env_type == "production":
        console_format = (
            "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}"
        )
        console_level = "INFO"
    else:
        console_format = (
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
        console_level = "DEBUG"
    
    logger.add(
        sys.stderr,
        format=console_format,
        level=console_level,
        colorize=(settings.env_type != "production"),
    )
    
    # ==================== 全量日志文件 ====================
    # 所有 DEBUG+ 日志，按 10MB 轮转，保留 30 天
    logger.add(
        str(LOG_DIR / "app.log"),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{line} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="30 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,  # 异步写入，不阻塞主线程
    )
    
    # ==================== 错误日志文件 ====================
    # 仅 WARNING+ 日志，单独存放便于监控告警
    logger.add(
        str(LOG_DIR / "error.log"),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{line} | {message}",
        level="WARNING",
        rotation="10 MB",
        retention="60 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
    )
    
    # ==================== 访问日志文件 ====================
    # 仅 [AccessLog] 标记的日志，按天轮转
    logger.add(
        str(LOG_DIR / "access.log"),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        level="DEBUG",
        rotation="00:00",  # 每天午夜轮转
        retention="14 days",
        compression="gz",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: "[AccessLog]" in record["message"],
    )
    
    # ==================== JSON 日志 (生产环境) ====================
    if settings.env_type == "production":
        logger.add(
            str(LOG_DIR / "app.json"),
            level="INFO",
            rotation="10 MB",
            retention="30 days",
            compression="gz",
            encoding="utf-8",
            enqueue=True,
            serialize=True,  # loguru 内置 JSON 序列化
        )
    
    logger.info(f"[LogConfig] Logging initialized | dir={LOG_DIR} | env={settings.env_type}")

