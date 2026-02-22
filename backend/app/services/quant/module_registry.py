"""
Module Registry — 模块注册表
==============================
LEAN 风格: 为每一层维护可选模块目录

每个模块定义包含:
- id:          唯一标识 (用于 YAML 配置)
- name:        显示名
- layer:       所属层 (alpha / portfolio / risk / execution)
- description: 功能描述
- params:      参数 schema (名称 + 类型 + 默认值 + 说明)

公开 API:
- list_modules(layer?)    → 列出某层 (或全部) 可用模块
- get_module(layer, id)   → 获取单个模块详情
- get_registry_summary()  → 返回每层模块数量摘要
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ParamSpec:
    """模块参数规格"""
    name: str
    type: str           # "float" | "int" | "str" | "bool"
    default: Any
    description: str
    min_value: Any = None
    max_value: Any = None


@dataclass
class ModuleInfo:
    """模块信息"""
    id: str
    name: str
    layer: str          # "alpha" | "portfolio" | "risk" | "execution"
    description: str
    params: List[ParamSpec] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的字典"""
        return {
            "id": self.id,
            "name": self.name,
            "layer": self.layer,
            "description": self.description,
            "params": [
                {
                    "name": p.name,
                    "type": p.type,
                    "default": p.default,
                    "description": p.description,
                    **({"min": p.min_value} if p.min_value is not None else {}),
                    **({"max": p.max_value} if p.max_value is not None else {}),
                }
                for p in self.params
            ],
        }


# ============================================================
# 注册表内容
# ============================================================

_REGISTRY: List[ModuleInfo] = [
    # ── Alpha 层 ──────────────────────────────────────────
    ModuleInfo(
        id="yaml_condition",
        name="技术指标条件",
        layer="alpha",
        description=(
            "基于技术指标 (RSI, MACD, EMA, 布林带等) 组合条件生成交易信号。"
            "支持 AND/OR 逻辑组合多个条件，灵活度高。"
        ),
        params=[
            ParamSpec("entry_operator", "str", "AND",
                      "入场条件逻辑: AND (全部满足) / OR (任一满足)"),
            ParamSpec("entry_conditions", "list", [],
                      "入场条件列表, 每项含 indicator/compare/value"),
            ParamSpec("exit_operator", "str", "OR",
                      "出场条件逻辑: AND / OR"),
            ParamSpec("exit_conditions", "list", [],
                      "出场条件列表"),
        ],
    ),
    ModuleInfo(
        id="ai_agent",
        name="AI 智能判断",
        layer="alpha",
        description=(
            "由 AI 大模型分析行情并生成交易信号。"
            "AI 会综合技术面、资金面、情绪面做出判断。"
        ),
        params=[
            ParamSpec("confidence_threshold", "float", 0.5,
                      "最低信心阈值, 低于此值的信号不执行",
                      min_value=0.1, max_value=1.0),
        ],
    ),

    # ── Portfolio 层 ──────────────────────────────────────
    ModuleInfo(
        id="fixed_percent",
        name="固定比例仓位",
        layer="portfolio",
        description=(
            "每次用可用余额的固定比例 (默认 10%) 开仓。"
            "简单可靠，适合稳健型交易者。"
        ),
        params=[
            ParamSpec("risk_percent", "float", 10.0,
                      "每次开仓使用余额的百分比",
                      min_value=1.0, max_value=50.0),
            ParamSpec("default_leverage", "int", 5,
                      "默认杠杆倍数",
                      min_value=1, max_value=20),
            ParamSpec("max_positions", "int", 5,
                      "最大同时持仓数",
                      min_value=1, max_value=20),
            ParamSpec("default_sl_pct", "float", 2.0,
                      "默认止损百分比",
                      min_value=0.5, max_value=10.0),
            ParamSpec("default_tp_pct", "float", 4.0,
                      "默认止盈百分比",
                      min_value=1.0, max_value=30.0),
        ],
    ),
    ModuleInfo(
        id="kelly",
        name="凯利公式仓位",
        layer="portfolio",
        description=(
            "根据凯利公式 (Kelly Criterion) 动态计算最优仓位大小。"
            "默认使用 Half-Kelly (半凯利) 降低波动风险。"
            "适合有一定历史胜率数据的策略。"
        ),
        params=[
            ParamSpec("kelly_fraction", "float", 0.5,
                      "凯利比例 (0.5 = Half-Kelly, 更保守)",
                      min_value=0.1, max_value=1.0),
            ParamSpec("max_risk_percent", "float", 25.0,
                      "单次最大仓位占比 (凯利上限)",
                      min_value=5.0, max_value=50.0),
            ParamSpec("default_leverage", "int", 5,
                      "默认杠杆倍数",
                      min_value=1, max_value=20),
            ParamSpec("odds_ratio", "float", 2.0,
                      "默认赔率 (止盈是止损的倍数)",
                      min_value=1.0, max_value=5.0),
            ParamSpec("max_positions", "int", 5,
                      "最大同时持仓数",
                      min_value=1, max_value=20),
        ],
    ),

    # ── Risk 层 ───────────────────────────────────────────
    ModuleInfo(
        id="standard",
        name="标准风控",
        layer="risk",
        description=(
            "综合风控审批：杠杆限制、单笔保证金限制、日亏损熔断、"
            "持仓数限制、总敞口限制、风险回报比检查。"
        ),
        params=[
            ParamSpec("max_leverage", "int", 20,
                      "允许的最大杠杆",
                      min_value=1, max_value=125),
            ParamSpec("max_daily_loss_pct", "float", 10.0,
                      "日最大亏损比例 (触发熔断)",
                      min_value=1.0, max_value=50.0),
            ParamSpec("max_positions", "int", 10,
                      "最大同时持仓数",
                      min_value=1, max_value=50),
            ParamSpec("max_daily_trades", "int", 20,
                      "日最大交易次数",
                      min_value=1, max_value=100),
            ParamSpec("max_single_margin_pct", "float", 30.0,
                      "单笔最大保证金占比",
                      min_value=5.0, max_value=100.0),
        ],
    ),

    # ── Execution 层 ──────────────────────────────────────
    ModuleInfo(
        id="market",
        name="市价单执行",
        layer="execution",
        description=(
            "以市价立即成交。速度最快，适合大多数场景。"
            "自动挂载止损止盈。"
        ),
        params=[],
    ),
    ModuleInfo(
        id="limit",
        name="限价单挂单",
        layer="execution",
        description=(
            "以指定价格挂单等待成交。适合想在更好价格入场的策略。"
            "通过偏移百分比自动计算挂单价格。"
        ),
        params=[
            ParamSpec("price_offset_pct", "float", -0.3,
                      "相对当前价的偏移% (负数=低于当前价挂买单, 正数=高于当前价挂卖单)",
                      min_value=-5.0, max_value=5.0),
        ],
    ),
    ModuleInfo(
        id="stop_market",
        name="条件触发市价单",
        layer="execution",
        description=(
            "价格触及指定条件后以市价成交。适合突破策略。"
            "例如：突破阻力位后自动市价做多。"
        ),
        params=[
            ParamSpec("trigger_offset_pct", "float", 0.2,
                      "触发价相对当前价的偏移% (正数=突破做多, 负数=跌破做空)",
                      min_value=-5.0, max_value=5.0),
        ],
    ),
]

# 按 (layer, id) 建索引
_INDEX: Dict[str, Dict[str, ModuleInfo]] = {}
for _m in _REGISTRY:
    _INDEX.setdefault(_m.layer, {})[_m.id] = _m


# ============================================================
# 公开 API
# ============================================================

def list_modules(layer: Optional[str] = None) -> List[ModuleInfo]:
    """
    列出可用模块

    Args:
        layer: 指定层 ("alpha"/"portfolio"/"risk"/"execution")
               为 None 时返回全部
    """
    if layer:
        return list(_INDEX.get(layer, {}).values())
    return list(_REGISTRY)


def get_module(layer: str, module_id: str) -> Optional[ModuleInfo]:
    """获取单个模块信息"""
    return _INDEX.get(layer, {}).get(module_id)


def get_registry_summary() -> Dict[str, int]:
    """返回每层模块数量"""
    return {layer: len(modules) for layer, modules in _INDEX.items()}
