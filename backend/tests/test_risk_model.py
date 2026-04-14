"""
风控配置(Risk Config)单元测试
=================================
测试 core/risk_config.py 的配置加载、默认值、类型安全、热加载逻辑。

纯单元测试, 不依赖数据库和网络请求。

运行方式:
    cd backend
    python -m pytest tests/test_risk_model.py -v
"""

import sys
import os
import importlib.util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
from pathlib import Path

import pytest

# 直接加载模块文件，绕过 app/core/__init__.py 的重依赖链
_mod_path = os.path.join(os.path.dirname(__file__), "..", "app", "core", "risk_config.py")
_spec = importlib.util.spec_from_file_location("risk_config", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

RiskConfigLoader = _mod.RiskConfigLoader
_DEFAULTS = _mod._DEFAULTS
_sanitize = _mod._sanitize


# ============================================
# A. 默认值测试
# ============================================

class TestDefaults:
    """风控参数默认值"""

    def test_defaults_exist(self):
        """默认配置包含所有必须字段"""
        required_keys = [
            "max_leverage", "max_daily_loss_pct", "risk_percent",
            "default_leverage", "max_positions", "default_sl_pct",
            "default_tp_pct", "kelly_fraction", "max_risk_percent",
            "blacklist",
        ]
        for key in required_keys:
            assert key in _DEFAULTS, f"缺少默认值: {key}"

    def test_default_max_leverage(self):
        """默认最大杠杆 = 20"""
        assert _DEFAULTS["max_leverage"] == 20

    def test_default_leverage(self):
        """默认杠杆 = 5"""
        assert _DEFAULTS["default_leverage"] == 5

    def test_default_max_positions(self):
        """默认最大持仓 = 5"""
        assert _DEFAULTS["max_positions"] == 5

    def test_default_sl_tp(self):
        """默认止损 2%, 止盈 4%"""
        assert _DEFAULTS["default_sl_pct"] == 2.0
        assert _DEFAULTS["default_tp_pct"] == 4.0

    def test_default_blacklist_empty(self):
        """默认黑名单为空列表"""
        assert _DEFAULTS["blacklist"] == []


# ============================================
# B. sanitize 类型安全测试
# ============================================

class TestSanitize:
    """类型安全处理"""

    def test_converts_string_to_int(self):
        """字符串应被转换为整数"""
        data = dict(_DEFAULTS)
        data["max_leverage"] = "50"
        result = _sanitize(data)
        assert isinstance(result["max_leverage"], int)
        assert result["max_leverage"] == 50

    def test_converts_string_to_float(self):
        """字符串应被转换为浮点数"""
        data = dict(_DEFAULTS)
        data["risk_percent"] = "15.5"
        result = _sanitize(data)
        assert isinstance(result["risk_percent"], float)
        assert result["risk_percent"] == 15.5

    def test_invalid_blacklist_reset(self):
        """非列表的 blacklist 应被重置为空列表"""
        data = dict(_DEFAULTS)
        data["blacklist"] = "not-a-list"
        result = _sanitize(data)
        assert result["blacklist"] == []

    def test_none_blacklist_reset(self):
        """None blacklist 应被重置为空列表"""
        data = dict(_DEFAULTS)
        data["blacklist"] = None
        result = _sanitize(data)
        assert result["blacklist"] == []

    def test_valid_blacklist_preserved(self):
        """有效列表 blacklist 保留"""
        data = dict(_DEFAULTS)
        data["blacklist"] = ["DOGEUSDT", "SHIBUSDT"]
        result = _sanitize(data)
        assert result["blacklist"] == ["DOGEUSDT", "SHIBUSDT"]

    def test_all_fields_correct_types(self):
        """sanitize 后所有数值字段类型正确"""
        data = {
            "max_leverage": "20",
            "max_daily_loss_pct": "10.0",
            "risk_percent": "10",
            "default_leverage": "5",
            "max_positions": "5",
            "default_sl_pct": "2.0",
            "default_tp_pct": "4.0",
            "kelly_fraction": "0.5",
            "max_risk_percent": "25",
            "blacklist": [],
        }
        result = _sanitize(data)
        assert isinstance(result["max_leverage"], int)
        assert isinstance(result["default_leverage"], int)
        assert isinstance(result["max_positions"], int)
        assert isinstance(result["max_daily_loss_pct"], float)
        assert isinstance(result["risk_percent"], float)
        assert isinstance(result["default_sl_pct"], float)
        assert isinstance(result["default_tp_pct"], float)
        assert isinstance(result["kelly_fraction"], float)
        assert isinstance(result["max_risk_percent"], float)


# ============================================
# C. Loader 加载测试 (内存模式)
# ============================================

class TestRiskConfigLoader:
    """配置加载器"""

    def test_load_without_file_returns_defaults(self):
        """配置文件不存在时返回默认值"""
        loader = RiskConfigLoader(path=Path("/nonexistent/path/config.yaml"))
        cfg = loader.load()
        assert cfg["max_leverage"] == _DEFAULTS["max_leverage"]
        assert cfg["risk_percent"] == _DEFAULTS["risk_percent"]

    def test_load_from_yaml_file(self):
        """从 YAML 文件加载并覆盖默认值"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("max_leverage: 50\nrisk_percent: 20.0\n")
            f.flush()
            tmp_path = Path(f.name)

        try:
            loader = RiskConfigLoader(path=tmp_path)
            cfg = loader.load()
            assert cfg["max_leverage"] == 50
            assert cfg["risk_percent"] == 20.0
            # 未覆盖的字段应保持默认值
            assert cfg["default_leverage"] == _DEFAULTS["default_leverage"]
        finally:
            os.unlink(tmp_path)

    def test_hot_reload_cached(self):
        """文件未变时返回缓存 (mtime 检查)"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("max_leverage: 30\n")
            f.flush()
            tmp_path = Path(f.name)

        try:
            loader = RiskConfigLoader(path=tmp_path)
            cfg1 = loader.load()
            cfg2 = loader.load()
            # 两次应该是同一个对象 (缓存命中)
            assert cfg1 is cfg2
        finally:
            os.unlink(tmp_path)

    def test_get_single_key(self):
        """get() 获取单个配置项"""
        loader = RiskConfigLoader(path=Path("/nonexistent.yaml"))
        assert loader.get("max_leverage") == _DEFAULTS["max_leverage"]
        assert loader.get("nonexistent_key", "fallback") == "fallback"


# ============================================
# D. 风控参数边界验证
# ============================================

class TestRiskParameterBounds:
    """风控参数的逻辑合理性检查"""

    def test_sl_less_than_tp(self):
        """默认止损比例 < 止盈比例 (风险回报 > 1)"""
        assert _DEFAULTS["default_sl_pct"] < _DEFAULTS["default_tp_pct"]

    def test_risk_percent_within_max(self):
        """默认风险比例 ≤ 最大风险比例"""
        assert _DEFAULTS["risk_percent"] <= _DEFAULTS["max_risk_percent"]

    def test_default_leverage_within_max(self):
        """默认杠杆 ≤ 最大杠杆"""
        assert _DEFAULTS["default_leverage"] <= _DEFAULTS["max_leverage"]

    def test_kelly_fraction_range(self):
        """Kelly 系数应在 (0, 1] 范围内"""
        assert 0 < _DEFAULTS["kelly_fraction"] <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
