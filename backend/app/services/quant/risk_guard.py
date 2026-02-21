"""
Risk Guard — 兼容性垫片
========================
⚠️ 已废弃 — 请直接使用 app.services.risk.risk_model.RiskModel

所有逻辑已迁移至 RiskModel, 此文件仅保留旧的 import 路径兼容性。
"""

from app.services.risk.risk_model import RiskModel, RiskCheckResult  # noqa: F401

# 旧名字的别名 — 保持向后兼容
RiskGuard = RiskModel

# 全局单例 (旧代码可能 from risk_guard import risk_guard)
risk_guard = RiskModel()
