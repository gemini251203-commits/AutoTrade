"""
Agent Tools Package
====================
AI 交易代理的工具集 — 拆分自原 tools.py (122KB / 3226行)

每个工具是一个 async 函数，调用现有后端服务完成实际操作。
工具的输入输出都是简单的 dict/str，方便 AI 解析。

外部使用方式不变:
    from app.services.agent.tools import TOOL_REGISTRY
    from app.services.agent.tools import agent_source_var, agent_name_var
"""

# 核心注册表和上下文变量
from ._registry import (
    TOOL_REGISTRY,
    register_tool,
    agent_source_var,
    agent_name_var,
    prompt_template_id_var,
)

# 导入所有子模块以触发 @register_tool 注册
from . import market       # get_price, get_funding_rate, get_klines
from . import account      # get_balance, get_positions, get_open_orders
from . import trading      # place_order, close_position, change_leverage, cancel_order
from . import analysis     # get_indicators, analyze_market, query_memories
from . import strategy     # list/get/delete/evaluate/run/create/update_strategy, list_modules, create_pipeline_strategy
from . import trend        # analyze_trend, analyze_trend_now, get_trend_result
from . import grid         # manage_grid
from . import journal      # get_trade_journal, get_trading_logs
from . import news_alerts  # get_news, get_market_sentiment, list/create/update_alert,
                           # analyze_news_impact, auto_generate_alerts,
                           # search_historical_minutes, set_wake_conditions

# ★ 直接导出 — 外部代码通过 `from app.services.agent.tools import get_klines` 使用
from .market import get_klines

__all__ = [
    "TOOL_REGISTRY",
    "register_tool",
    "agent_source_var",
    "agent_name_var",
    "prompt_template_id_var",
    "get_klines",
]
