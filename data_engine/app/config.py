"""
Data Engine Configuration
==========================
从环境变量读取配置
"""

import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Data Engine 配置"""
    
    # 环境类型
    env_type: str = "local"
    
    # 代理配置
    http_proxy: str = ""
    https_proxy: str = ""
    
    # 交易所 API
    binance_api_key: str = ""
    binance_api_secret: str = ""
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # 日志
    log_level: str = "INFO"
    
    # 监控的交易对
    @property
    def watched_symbols(self) -> List[str]:
        """获取监控的交易对列表"""
        return [
            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "XRPUSDT",
        ]
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
