"""
Production Logging Configuration
================================
生产环境日志配置

功能:
1. 按日期分割日志文件
2. 分离错误日志
3. JSON 格式便于分析
4. 自动清理旧日志
"""

import sys
from pathlib import Path
from loguru import logger


def setup_production_logging(
    log_dir: str = "logs",
    rotation: str = "00:00",  # 每天 0 点轮转
    retention: str = "30 days",  # 保留 30 天
    compression: str = "zip",
):
    """
    配置生产日志
    
    Args:
        log_dir: 日志目录
        rotation: 轮转时间
        retention: 保留时间
        compression: 压缩格式
    """
    # 创建日志目录
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # 移除默认 handler
    logger.remove()
    
    # 控制台输出 (简化格式)
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )
    
    # 主日志文件 (所有级别)
    logger.add(
        log_path / "app_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        compression=compression,
        encoding="utf-8",
    )
    
    # 错误日志 (单独保存)
    logger.add(
        log_path / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}\n{exception}",
        rotation=rotation,
        retention=retention,
        compression=compression,
        encoding="utf-8",
    )
    
    # JSON 格式 (便于日志分析系统)
    logger.add(
        log_path / "app_{time:YYYY-MM-DD}.json",
        level="INFO",
        format="{message}",  # serialize 会覆盖
        rotation=rotation,
        retention=retention,
        compression=compression,
        serialize=True,  # JSON 格式
    )
    
    logger.info("Production logging configured")
    logger.info(f"Log directory: {log_path.absolute()}")


# 自动配置 (如果是主模块)
if __name__ == "__main__":
    setup_production_logging()
    
    # 测试
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    
    try:
        raise ValueError("Test exception")
    except Exception:
        logger.exception("Exception with traceback")
