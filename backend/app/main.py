"""
Backend Core - Main Entry Point
================================
FastAPI 应用入口
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger

from app.core.config import settings
from app.core.log_config import setup_logging
from app.db.session import init_db
from app.api import auth, wallet, order, task, market, ai, position, risk, grid, user_config, admin, ws
from app.middleware.error_handler import setup_error_handlers
from app.middleware.access_logger import AccessLoggerMiddleware
from app.core.rate_limit import RateLimitMiddleware
from app.core.startup_validator import validate_startup_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 📋 初始化日志系统 (最先执行)
    setup_logging()
    
    logger.info("=" * 50)
    logger.info("AutoTrade Backend Core Starting...")
    logger.info(f"Environment: {settings.env_type}")
    logger.info("=" * 50)
    
    # 🔒 启动配置验证
    await validate_startup_config()
    
    # 初始化数据库
    await init_db()
    logger.info("Database initialized")
    
    # 初始化默认管理员账户
    from app.api.auth import init_default_admin
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await init_default_admin(session)
    
    # 启动市场数据采集器
    from app.services.market_collector import market_collector
    await market_collector.start()
    logger.info("Market Collector started")
    
    # 🔥 启动实时价格流 (WebSocket)
    from app.services.price_stream import price_stream
    await price_stream.start()
    logger.info("Price Stream (WebSocket) started")
    
    yield
    
    # ==================== Graceful Shutdown ====================
    logger.info("Backend Core shutting down...")
    
    # 停止实时价格流
    await price_stream.stop()
    logger.info("Price Stream stopped")
    
    # 停止市场数据采集器
    await market_collector.stop()
    logger.info("Market Collector stopped")
    
    # 关闭 Redis 连接
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url)
        await r.close()
        logger.info("Redis connection closed")
    except Exception:
        pass
    
    logger.info("All resources released. Goodbye!")


# 创建 FastAPI 应用
app = FastAPI(
    title="AutoTrade API",
    description="AI-Powered Cryptocurrency Trading System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置 (生产环境白名单)
allowed_origins = [
    "http://localhost:5173",     # Vite dev server
    "http://localhost:3000",     # 备用端口
    "http://127.0.0.1:5173",
]
# 生产环境: 从 CORS_ORIGINS 环境变量读取
if hasattr(settings, 'cors_origins') and settings.cors_origins:
    allowed_origins = [o.strip() for o in settings.cors_origins.split(',')]
elif settings.env_type == 'production':
    # 生产环境默认只允许同源 + 前端 Nginx 代理的请求
    allowed_origins = ["*"]  # Docker 内部通过 Nginx 代理，允许所有

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 📦 Gzip 压缩 (K线数据等大响应受益明显)
app.add_middleware(GZipMiddleware, minimum_size=500)  # >500B 才压缩

# 🔥 全局错误处理
setup_error_handlers(app)

# 🔒 速率限制 (120 req/min per IP)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=120,
    burst_size=20,
    exclude_paths=["/health", "/", "/docs", "/openapi.json", "/api/market/", "/api/ws/"],
)

# 📝 访问日志 (最外层，记录所有请求含被限流的)
app.add_middleware(
    AccessLoggerMiddleware,
    exclude_paths=["/health", "/", "/docs", "/openapi.json", "/redoc"],
    slow_threshold_ms=1000,
)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(wallet.router, prefix="/api/wallet", tags=["Wallet"])
app.include_router(order.router, prefix="/api/order", tags=["Order"])
app.include_router(task.router, prefix="/api/task", tags=["Task"])
app.include_router(market.router, prefix="/api/market", tags=["Market"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(position.router, prefix="/api/position", tags=["Position"])
app.include_router(risk.router, prefix="/api/risk", tags=["Risk"])
app.include_router(grid.router, prefix="/api/grid", tags=["Grid"])
app.include_router(user_config.router, prefix="/api/user", tags=["User Config"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(ws.router, prefix="/api/ws", tags=["WebSocket"])


@app.get("/")
async def root():
    """健康检查"""
    return {
        "service": "AutoTrade Backend Core",
        "status": "healthy",
        "version": "1.0.0",
    }


@app.get("/health")
async def health_check():
    """详细健康检查 — 实际测试 DB + Redis 连通性"""
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text
    import redis.asyncio as aioredis
    
    checks = {}
    overall = True
    
    # 检查数据库
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"
        overall = False
    
    # 检查 Redis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.close()
        checks["redis"] = "connected"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"
        overall = False
    
    return {
        "status": "healthy" if overall else "degraded",
        **checks,
        "environment": settings.env_type,
        "trading_mode": settings.trading_mode,
    }
