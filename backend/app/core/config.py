"""
Backend Core Configuration
===========================
从环境变量读取配置

配置优先级:
1. 系统环境变量 (最高)
2. .env 文件 (backend/.env)
3. 默认值 (最低)
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


# 计算 backend/.env 的绝对路径
# 无论从哪个目录运行，都能找到正确的 .env 文件
BACKEND_DIR = Path(__file__).parent.parent.parent  # backend/
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Backend Core 配置"""
    
    # 环境类型
    env_type: str = "local"
    
    # 交易模式
    trading_mode: str = "simulation"  # simulation / live
    simulation_initial_balance: str = "1000"  # 模拟盘初始余额
    
    # 代理配置
    use_proxy: bool = False
    proxy_url: str = ""
    http_proxy: str = ""
    https_proxy: str = ""
    
    # 数据库 (默认使用 PostgreSQL)
    database_url: str = "postgresql+asyncpg://autotrade:autotrade_secret_2026@127.0.0.1:5432/autotrade"
    
    # Redis
    redis_url: str = "redis://127.0.0.1:6379/0"
    
    # 交易所 API
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True
    
    # JWT 配置
    jwt_secret_key: str = "your-secret-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    
    # AI 配置
    ai_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "deepseek-r1:14b"
    ollama_vision_model: str = "minicpm-v"
    deepseek_api_key: str = ""
    
    # 新闻模块
    cryptopanic_api_key: str = ""  # CryptoPanic API Key (legacy)
    cryptocompare_api_key: str = ""  # CryptoCompare API Key (推荐)
    
    # 深度回填配置
    deep_backfill_enabled: bool = True       # 是否启用深度回填
    deep_backfill_days: int = 365            # 回填天数
    deep_backfill_intervals: str = "1h,4h,1d"  # 回填周期列表
    
    # 多智能体分析
    multi_agent_enabled: bool = True         # 是否启用多智能体
    multi_agent_debate_rounds: int = 1       # 辩论轮数
    
    # 日志
    log_level: str = "INFO"
    
    # CORS 白名单 (逗号分隔, 如 "http://example.com,https://app.example.com")
    cors_origins: str = ""
    
    # Pydantic v2 配置
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),  # 使用绝对路径
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # 忽略多余的环境变量
    )


# 全局配置实例
settings = Settings()
