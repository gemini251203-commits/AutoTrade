"""
Agent Tools — 注册表与共用基础设施
===================================
从原 tools.py (122KB) 抽取的核心基础模块。

所有工具子模块从此处导入 register_tool 装饰器。
"""

import contextvars
from typing import Dict, Any

# ==================== 来源上下文 ====================
# Hub/Daemon 调用前设置此变量，tools 自动使用正确的 note 前缀
agent_source_var = contextvars.ContextVar('agent_source', default='agent')
# Agent 名称上下文 — 由 brain.py 设置，用于订单归属追踪
agent_name_var = contextvars.ContextVar('agent_name', default='')
# 提示词模板 ID 上下文 — 由 brain.py/daemon 设置，用于提示词收益追踪
prompt_template_id_var = contextvars.ContextVar('prompt_template_id', default=0)

# ==================== 工具注册表 ====================

TOOL_REGISTRY: Dict[str, Any] = {}


def register_tool(func):
    """注册工具到全局注册表"""
    TOOL_REGISTRY[func.__name__] = func
    return func
