"""
Startup Configuration Validator
=================================
应用启动时验证配置完整性

功能:
1. 检查必需的环境变量
2. 验证配置格式
3. 生产环境安全检查
4. 输出友好的启动日志

调用方式:
    from app.core.startup_validator import validate_startup_config
    await validate_startup_config()
"""

from loguru import logger

from app.core.config import settings


async def validate_startup_config():
    """
    验证启动配置
    
    在 main.py 的 lifespan 中调用。
    发现严重问题时输出 WARNING 但不阻止启动（graceful degradation）。
    """
    logger.info("[StartupValidator] Validating configuration...")
    
    issues = []
    warnings = []
    
    # ==================== 必需配置检查 ====================
    
    # 数据库 URL
    if not settings.database_url:
        issues.append("DATABASE_URL is not configured")
    elif "postgresql" not in settings.database_url:
        warnings.append("DATABASE_URL does not appear to be PostgreSQL")
    
    # Redis URL
    if not settings.redis_url:
        issues.append("REDIS_URL is not configured")
    elif not settings.redis_url.startswith("redis://"):
        warnings.append(f"REDIS_URL format looks unusual: {settings.redis_url[:20]}...")
    
    # ==================== 安全检查 ====================
    
    # JWT Secret — 空值或已知不安全默认值
    _unsafe_jwt_keys = {"", "your-secret-key", "your-secret-key-change-in-production"}
    if settings.jwt_secret_key in _unsafe_jwt_keys:
        issues.append(
            "JWT_SECRET_KEY is empty or using a known insecure default! "
            "Please set a random key (e.g. python -c \"import secrets; print(secrets.token_hex(32))\")"
        )
    elif len(settings.jwt_secret_key) < 32:
        warnings.append("JWT_SECRET_KEY is shorter than 32 characters, consider using a longer key")
    
    # ==================== 交易所配置 ====================
    
    if settings.trading_mode == "live":
        if not settings.binance_api_key:
            issues.append("BINANCE_API_KEY is required for live trading")
        if not settings.binance_api_secret:
            issues.append("BINANCE_API_SECRET is required for live trading")
    
    # ==================== 输出结果 ====================
    
    if issues:
        logger.warning("=" * 50)
        logger.warning("[StartupValidator] ⚠️  Configuration issues found:")
        for issue in issues:
            logger.warning(f"  ❌ {issue}")
        logger.warning("=" * 50)
    
    if warnings:
        for warning in warnings:
            logger.info(f"[StartupValidator] ⚡ {warning}")
    
    if not issues and not warnings:
        logger.info("[StartupValidator] ✅ All configuration checks passed")
    
    # 输出运行环境摘要
    logger.info(
        f"[StartupValidator] Environment: {settings.env_type} | "
        f"Trading: {settings.trading_mode} | "
        f"AI: {settings.ai_provider} | "
        f"Deep Backfill: {'ON' if settings.deep_backfill_enabled else 'OFF'}"
    )
    
    return len(issues) == 0
