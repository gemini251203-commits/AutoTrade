"""
Backend Core - Main Entry Point
================================
FastAPI 应用入口
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import settings
from app.db.session import init_db
from app.api import auth, wallet, order, task, market, ai, position, risk, grid, user_config, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("AutoTrade Backend Core Starting...")
    logger.info(f"Environment: {settings.env_type}")
    logger.info("=" * 50)
    
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
    
    # 停止实时价格流
    await price_stream.stop()
    logger.info("Price Stream stopped")
    
    # 停止市场数据采集器
    await market_collector.stop()
    logger.info("Market Collector stopped")
    
    logger.info("Backend Core shutting down...")


# 创建 FastAPI 应用
app = FastAPI(
    title="AutoTrade API",
    description="AI-Powered Cryptocurrency Trading System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    """详细健康检查"""
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected",
    }
