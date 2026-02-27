"""
Risk Config Loader — 风控参数热加载器
=======================================
从 risk_config.yaml 读取风控参数，支持热加载（文件修改后自动刷新）。

工作机制:
    每次调用 load() 时检查文件 mtime:
    - 文件未变 → 返回内存缓存 (零开销)
    - 文件已变 → 重新读取并刷新缓存

使用方式:
    from app.core.risk_config import risk_config
    cfg = risk_config.load()
    print(cfg["max_leverage"])   # 20
"""

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from loguru import logger


# 配置文件路径: backend/risk_config.yaml
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "risk_config.yaml"

# 默认值 (当配置文件不存在或字段缺失时使用)
_DEFAULTS: Dict[str, Any] = {
    "max_leverage": 20,
    "max_daily_loss_pct": 10.0,
    "risk_percent": 10.0,
    "default_leverage": 5,
    "max_positions": 5,
    "default_sl_pct": 2.0,
    "default_tp_pct": 4.0,
    "kelly_fraction": 0.5,
    "max_risk_percent": 25.0,
    "blacklist": [],
}


class RiskConfigLoader:
    """
    风控配置热加载器 (单例)
    
    特性:
    - 基于文件 mtime 的变更检测，无变化时零 IO
    - 缺失字段自动填充默认值
    - 文件不存在时使用全默认值
    """
    
    def __init__(self, path: Path = _CONFIG_PATH):
        self._path = path
        self._cache: Dict[str, Any] = dict(_DEFAULTS)
        self._mtime: float = 0
    
    def load(self) -> Dict[str, Any]:
        """
        加载配置 (热加载)
        
        Returns:
            配置字典，保证包含所有字段
        """
        try:
            if not self._path.exists():
                return self._cache
            
            current_mtime = os.path.getmtime(self._path)
            
            if current_mtime == self._mtime:
                return self._cache
            
            # 文件已修改，重新加载
            with open(self._path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            
            # 合并默认值 (用户配置优先)
            merged = dict(_DEFAULTS)
            merged.update(raw)
            
            # 类型安全
            merged["max_leverage"] = int(merged["max_leverage"])
            merged["max_daily_loss_pct"] = float(merged["max_daily_loss_pct"])
            merged["risk_percent"] = float(merged["risk_percent"])
            merged["default_leverage"] = int(merged["default_leverage"])
            merged["max_positions"] = int(merged["max_positions"])
            merged["default_sl_pct"] = float(merged["default_sl_pct"])
            merged["default_tp_pct"] = float(merged["default_tp_pct"])
            merged["kelly_fraction"] = float(merged["kelly_fraction"])
            merged["max_risk_percent"] = float(merged["max_risk_percent"])
            
            if not isinstance(merged["blacklist"], list):
                merged["blacklist"] = []
            
            self._cache = merged
            self._mtime = current_mtime
            
            logger.info(
                f"[RiskConfig] ♻️ 配置已热加载: "
                f"max_lev={merged['max_leverage']}x, "
                f"risk={merged['risk_percent']}%, "
                f"sl={merged['default_sl_pct']}%, "
                f"tp={merged['default_tp_pct']}%, "
                f"blacklist={merged['blacklist']}"
            )
            
        except Exception as e:
            logger.error(f"[RiskConfig] 加载失败，使用缓存值: {e}")
        
        return self._cache
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取单个配置项"""
        return self.load().get(key, default)


# 全局单例
risk_config = RiskConfigLoader()
