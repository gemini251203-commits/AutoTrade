"""
Tool Registry API
===================
提供系统工具全集查询接口，支持前端可视化工具权限控制。

GET /api/tools → 返回所有已注册工具的清单（名称、描述、分类、读写类型）
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import inspect

router = APIRouter(tags=["Tools"])


# ==================== 工具元数据分类表 ====================
# key = 函数名, value = (category, access_type)
# access_type: "read" = 只读查询, "execute" = 执行操作(下单/修改/删除)

TOOL_METADATA = {
    # 行情工具 (只读)
    "get_price":            ("行情数据", "read"),
    "get_funding_rate":     ("行情数据", "read"),
    "get_klines":           ("行情数据", "read"),
    
    # 账户工具 (只读)
    "get_balance":          ("账户信息", "read"),
    "get_positions":        ("账户信息", "read"),
    "get_open_orders":      ("账户信息", "read"),
    
    # 交易工具 (执行)
    "place_order":          ("交易执行", "execute"),
    "close_position":       ("交易执行", "execute"),
    "cancel_order":         ("交易执行", "execute"),
    
    # 分析工具 (只读)
    "get_indicators":       ("技术分析", "read"),
    "analyze_market":       ("技术分析", "read"),
    "query_memories":       ("技术分析", "read"),
    "analyze_trend":        ("技术分析", "read"),
    "analyze_trend_now":    ("技术分析", "read"),
    "get_trend_result":     ("技术分析", "read"),
    
    # 策略管理 (混合)
    "list_strategies":      ("策略管理", "read"),
    "get_strategy_detail":  ("策略管理", "read"),
    "evaluate_strategy":    ("策略管理", "read"),
    "list_modules":         ("策略管理", "read"),
    "run_strategy":         ("策略管理", "execute"),
    "create_strategy":      ("策略管理", "execute"),
    "update_strategy":      ("策略管理", "execute"),
    "delete_strategy":      ("策略管理", "execute"),
    "create_pipeline_strategy": ("策略管理", "execute"),
    
    # 自动交易管理 (执行)
    "manage_autopilot":     ("自动交易", "execute"),
    "start_autopilot":      ("自动交易", "execute"),
    "stop_autopilot":       ("自动交易", "execute"),
    "get_autopilot_status": ("自动交易", "read"),
    "get_trading_logs":     ("自动交易", "read"),
    
    # 网格交易 (执行)
    "manage_grid":          ("网格交易", "execute"),
    
    # 交易日记 (只读)
    "get_trade_journal":    ("交易日记", "read"),
    
    # 新闻工具 (混合)
    "get_news":             ("新闻情报", "read"),
    "get_market_sentiment": ("新闻情报", "read"),
    "list_alerts":          ("新闻情报", "read"),
    "create_alert":         ("新闻情报", "execute"),
    "update_alert":         ("新闻情报", "execute"),
    "analyze_news_impact":  ("新闻情报", "read"),
    "auto_generate_alerts": ("新闻情报", "execute"),
    
    # 董事会记忆 (只读)
    "search_historical_minutes": ("董事会记忆", "read"),
}


# ==================== Schema ====================

class ToolInfo(BaseModel):
    """单个工具的信息"""
    name: str               # 工具函数名
    description: str        # 工具描述 (来自 docstring)
    category: str           # 分类 (行情数据/交易执行/策略管理...)
    access_type: str        # read = 只读, execute = 执行操作
    parameters: list        # 参数列表 (排除 db/user_id)


class ToolParameter(BaseModel):
    """工具参数"""
    name: str
    type: str
    default: Optional[str] = None
    required: bool = False


class ToolListResponse(BaseModel):
    """工具全集响应"""
    tools: List[ToolInfo]
    total: int
    categories: dict        # { "行情数据": 3, "交易执行": 3, ... }


# ==================== Route ====================

@router.get("/", response_model=ToolListResponse)
async def list_all_tools():
    """
    获取系统所有已注册的 AI 工具清单
    
    返回每个工具的名称、描述、分类和读写类型。
    前端可用此接口渲染 Checkbox 权限面板。
    """
    from app.services.agent.tools import TOOL_REGISTRY
    
    tools = []
    categories = {}
    
    for name, func in TOOL_REGISTRY.items():
        # 获取元数据
        meta = TOOL_METADATA.get(name, ("其他", "read"))
        category, access_type = meta
        
        # 从函数签名提取参数
        sig = inspect.signature(func)
        params = []
        for pname, param in sig.parameters.items():
            if pname in ("db", "user_id"):
                continue
            
            annotation = param.annotation
            if annotation == int or annotation == float:
                ptype = "number"
            elif annotation == bool:
                ptype = "boolean"
            else:
                ptype = "string"
            
            params.append({
                "name": pname,
                "type": ptype,
                "default": str(param.default) if param.default != inspect.Parameter.empty else None,
                "required": param.default == inspect.Parameter.empty,
            })
        
        # 清理 docstring
        doc = (func.__doc__ or name).strip().split("\n")[0].strip()
        
        tools.append(ToolInfo(
            name=name,
            description=doc,
            category=category,
            access_type=access_type,
            parameters=params,
        ))
        
        # 统计分类
        categories[category] = categories.get(category, 0) + 1
    
    # 按分类排序
    tools.sort(key=lambda t: (t.category, t.access_type, t.name))
    
    return ToolListResponse(
        tools=tools,
        total=len(tools),
        categories=categories,
    )
