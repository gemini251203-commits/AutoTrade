"""
Risk Config Loader — 风控参数热加载器
=======================================
从 risk_config.yaml 读取风控参数，支持热加载（文件修改后自动刷新）。
支持 per-user 配置隔离 (risk_config_user_{id}.yaml)。

工作机制:
    每次调用 load() 时检查文件 mtime:
    - 文件未变 → 返回内存缓存 (零开销)
    - 文件已变 → 重新读取并刷新缓存

使用方式:
    from app.core.risk_config import risk_config
    cfg = risk_config.load()                  # 全局默认
    cfg = risk_config.load_for_user(user_id)  # 按用户隔离
"""

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from loguru import logger


# 配置文件路径: backend/risk_config.yaml
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _CONFIG_DIR / "risk_config.yaml"

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


def _sanitize(merged: dict) -> dict:
    """类型安全处理"""
    merged["max_leverage"] = int(merged.get("max_leverage", 20))
    merged["max_daily_loss_pct"] = float(merged.get("max_daily_loss_pct", 10.0))
    merged["risk_percent"] = float(merged.get("risk_percent", 10.0))
    merged["default_leverage"] = int(merged.get("default_leverage", 5))
    merged["max_positions"] = int(merged.get("max_positions", 5))
    merged["default_sl_pct"] = float(merged.get("default_sl_pct", 2.0))
    merged["default_tp_pct"] = float(merged.get("default_tp_pct", 4.0))
    merged["kelly_fraction"] = float(merged.get("kelly_fraction", 0.5))
    merged["max_risk_percent"] = float(merged.get("max_risk_percent", 25.0))
    if not isinstance(merged.get("blacklist"), list):
        merged["blacklist"] = []
    return merged


def _load_yaml(path: Path) -> dict:
    """从 YAML 文件读取配置"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class RiskConfigLoader:
    """
    风控配置热加载器 (单例)
    
    特性:
    - 基于文件 mtime 的变更检测，无变化时零 IO
    - 缺失字段自动填充默认值
    - 支持 per-user 配置隔离
    """
    
    def __init__(self, path: Path = _CONFIG_PATH):
        self._path = path
        self._cache: Dict[str, Any] = dict(_DEFAULTS)
        self._mtime: float = 0
        self._user_cache: Dict[int, Dict[str, Any]] = {}
        self._user_mtime: Dict[int, float] = {}
    
    def _user_path(self, user_id: int) -> Path:
        """获取用户专属配置文件路径"""
        # Docker 中使用 /app/risk_configs/ 持久卷
        user_dir = Path("/app/risk_configs") if Path("/app/risk_configs").exists() else _CONFIG_DIR
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / f"risk_config_user_{user_id}.yaml"
    
    def load(self) -> Dict[str, Any]:
        """加载全局配置 (热加载)"""
        try:
            if not self._path.exists():
                return self._cache
            
            current_mtime = os.path.getmtime(self._path)
            if current_mtime == self._mtime:
                return self._cache
            
            raw = _load_yaml(self._path)
            merged = dict(_DEFAULTS)
            merged.update(raw)
            merged = _sanitize(merged)
            
            self._cache = merged
            self._mtime = current_mtime
            
        except Exception as e:
            logger.error(f"[RiskConfig] 加载失败，使用缓存值: {e}")
        
        return self._cache
    
    def load_for_user(self, user_id: int) -> Dict[str, Any]:
        """
        加载用户专属配置 (热加载)
        
        优先读取 risk_config_user_{id}.yaml，
        不存在则回退到全局配置。
        """
        user_path = self._user_path(user_id)
        
        if not user_path.exists():
            return self.load()
        
        try:
            current_mtime = os.path.getmtime(user_path)
            if self._user_mtime.get(user_id) == current_mtime and user_id in self._user_cache:
                return self._user_cache[user_id]
            
            # 以全局配置为底，用户配置覆盖
            base = dict(self.load())
            user_raw = _load_yaml(user_path)
            base.update(user_raw)
            base = _sanitize(base)
            
            self._user_cache[user_id] = base
            self._user_mtime[user_id] = current_mtime
            
            logger.info(f"[RiskConfig] 用户 {user_id} 配置已加载")
            return base
            
        except Exception as e:
            logger.warning(f"[RiskConfig] 用户 {user_id} 配置加载失败: {e}")
            return self.load()
    
    def save_for_user(self, user_id: int, cfg: dict, yaml_generator=None) -> None:
        """保存用户专属配置"""
        user_path = self._user_path(user_id)
        if yaml_generator:
            yaml_content = yaml_generator(cfg)
        else:
            yaml_content = yaml.dump(cfg, allow_unicode=True)
        with open(user_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
        # 清除缓存，下次读取时重新加载
        self._user_mtime.pop(user_id, None)
        self._user_cache.pop(user_id, None)
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取单个配置项 (全局)"""
        return self.load().get(key, default)


# 全局单例
risk_config = RiskConfigLoader()
