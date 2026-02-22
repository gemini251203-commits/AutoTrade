"""
Pipeline Builder — 策略组装器
=============================
将多模块配置 (YAML/Dict) 转换为 TradingPipeline 运行时对象。

支持解析:
- alphas: List[AlphaModel] (支持 yaml_condition, agent)
- portfolio: PortfolioModel (支持 fixed_percent 等)
- risk: RiskModel 
- execution: ExecutionModel
"""

import yaml
from typing import Dict, Any, List
from loguru import logger

from app.core.pipeline import TradingPipeline
from app.services.alpha.base import AlphaModel
from app.services.portfolio.model import PortfolioModel, FixedPercentModel
from app.services.risk.risk_model import RiskModel, RiskConfig
from app.services.execution.model import ExecutionModel

def build_pipeline_from_yaml(config: Dict[str, Any], user_id: int) -> TradingPipeline:
    """
    根据 pipeline yaml layout 创建 TradingPipeline 实例
    
    Args:
        config: 解析过并经过白名单校验的策略 config 字典
        user_id: 策略所属用户ID
        
    Returns:
        组装好的 TradingPipeline 实例
    """
    alphas: List[AlphaModel] = []
    
    # 解析 Alphas (信号生成层)
    alphas_config = config.get("alphas", [])
    if isinstance(alphas_config, list):
        for idx, alpha_cfg in enumerate(alphas_config):
            if not isinstance(alpha_cfg, dict):
                continue
                
            type_ = alpha_cfg.get("type", "")
            name = alpha_cfg.get("name", f"alpha_{idx}")
            
            if type_ == "yaml_condition":
                from app.services.alpha.yaml_alpha import YamlAlpha
                
                # 提取子策略配置
                sub_config = dict(alpha_cfg)
                if "name" not in sub_config:
                    sub_config["name"] = name
                if "symbol" not in sub_config:
                    sub_config["symbol"] = config.get("symbol", "BTCUSDT")
                if "interval" not in sub_config:
                    sub_config["interval"] = config.get("interval", "1h")
                    
                # 重新转回 YAML 给 YamlAlpha 使用（依赖内部 StrategyEngine 解析）
                yaml_str = yaml.dump(sub_config)
                alphas.append(YamlAlpha(yaml_config=yaml_str, strategy_name=name))
                
            elif type_ == "ai_agent":
                from app.services.alpha.agent_alpha import AgentAlpha
                # Agent Alpha 的执行逻辑可能是被动接收，或是未来的主动调优
                alphas.append(
                    AgentAlpha(
                        user_id=user_id, 
                        confidence_threshold=alpha_cfg.get("confidence_threshold", 0.5)
                    )
                )
            else:
                raise ValueError(
                    f"不支持的 Alpha 类型: '{type_}'。"
                    f"支持的类型: yaml_condition, ai_agent"
                )

    # 解析 Portfolio (仓位管理层)
    portfolio_cfg = config.get("portfolio", {})
    p_type = portfolio_cfg.get("type", "fixed_percent")
    portfolio_params = portfolio_cfg.get("params", {})
    
    portfolio: PortfolioModel
    if p_type == "fixed_percent":
        portfolio = FixedPercentModel(
            risk_percent=float(portfolio_params.get("risk_percent", 10.0)),
            default_leverage=int(portfolio_params.get("default_leverage", 5)),
            max_positions=int(portfolio_params.get("max_positions", 5)),
            default_sl_pct=float(portfolio_params.get("default_sl_pct", 2.0)),
            default_tp_pct=float(portfolio_params.get("default_tp_pct", 4.0)),
        )
    elif p_type == "kelly":
        from app.services.portfolio.model import KellyPortfolioModel
        portfolio = KellyPortfolioModel(
            kelly_fraction=float(portfolio_params.get("kelly_fraction", 0.5)),
            max_risk_percent=float(portfolio_params.get("max_risk_percent", 25.0)),
            default_leverage=int(portfolio_params.get("default_leverage", 5)),
            odds_ratio=float(portfolio_params.get("odds_ratio", 2.0)),
            max_positions=int(portfolio_params.get("max_positions", 5)),
            default_sl_pct=float(portfolio_params.get("default_sl_pct", 2.0)),
            default_tp_pct=float(portfolio_params.get("default_tp_pct", 4.0)),
        )
    else:
        raise ValueError(
            f"不支持的 Portfolio 类型: '{p_type}'。"
            f"支持的类型: fixed_percent, kelly"
        )

    # 解析 Risk (风控层)
    risk_cfg = config.get("risk", {})
    risk_params = risk_cfg.get("params", {})
    
    risk_config_obj = RiskConfig()
    
    if "max_leverage" in risk_params:
        risk_config_obj.max_leverage = int(risk_params["max_leverage"])
    if "max_daily_loss_pct" in risk_params:
        risk_config_obj.max_daily_loss_pct = float(risk_params["max_daily_loss_pct"])
    if "max_drawdown_pct" in risk_params:
        risk_config_obj.max_daily_loss_pct = float(risk_params["max_drawdown_pct"])
    if "max_positions" in risk_params:
        risk_config_obj.max_positions = int(risk_params["max_positions"])
    if "max_daily_trades" in risk_params:
        risk_config_obj.max_daily_trades = int(risk_params["max_daily_trades"])
    if "max_single_margin_pct" in risk_params:
        risk_config_obj.max_single_margin_pct = float(risk_params["max_single_margin_pct"])
        
    risk_model = RiskModel(config=risk_config_obj)

    # 解析 Execution (执行层)
    exec_cfg = config.get("execution", {})
    exec_type = exec_cfg.get("type", "market")
    exec_params = exec_cfg.get("params", {})
    
    execution = ExecutionModel()
    # 将执行类型和参数存储在 execution 上，供 process 时使用
    execution._order_type = exec_type  # market / limit / stop_market
    execution._exec_params = exec_params
    
    pipeline = TradingPipeline(
        alphas=alphas,
        portfolio=portfolio,
        risk=risk_model,
        execution=execution,
        user_id=user_id
    )
    
    logger.info(f"[PipelineBuilder] Successfully built pipeline for user_id={user_id} with {len(alphas)} alphas.")
    return pipeline
