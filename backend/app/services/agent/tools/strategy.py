"""
策略管理工具 — list/get/delete/evaluate/run/create/update_strategy, list_modules, create_pipeline_strategy
"""

import json
from decimal import Decimal
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.strategy import Strategy
from app.models.position import Position, PositionSide, PositionStatus
from app.models.wallet import Wallet
from app.core.time_utils import utc_now
from ._registry import register_tool, agent_source_var


# ==================== 辅助函数 ====================

async def _fetch_klines_map(symbol: str, timeframes: list) -> dict:
    """
    获取多时间框架 K 线数据
    
    Returns:
        {"1h": [klines...], "4h": [klines...], ...}
    """
    from app.core.network import net_manager

    klines_map = {}
    async with net_manager.get_client(timeout=15.0) as client:
        for tf in timeframes:
            try:
                resp = await client.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={
                        "symbol": symbol,
                        "interval": tf,
                        "limit": 200,
                    },
                )
                if resp.status_code == 200:
                    raw = resp.json()
                    if raw and len(raw) >= 20:
                        klines_map[tf] = [{
                            "open_time": k[0],
                            "open": float(k[1]),
                            "high": float(k[2]),
                            "low": float(k[3]),
                            "close": float(k[4]),
                            "volume": float(k[5]),
                            "close_time": k[6],
                            "quote_volume": float(k[7]),
                        } for k in raw]
            except Exception as e:
                logger.warning(f"[Tools] 获取 {tf} K线失败: {e}")
    return klines_map


def _calc_fixed_stops(
    current_price: Decimal,
    position_side,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> tuple:
    """计算固定百分比止损止盈"""
    if position_side.value == "long":
        stop_loss = current_price * (1 - Decimal(str(stop_loss_pct)) / 100) if stop_loss_pct else None
        take_profit = current_price * (1 + Decimal(str(take_profit_pct)) / 100) if take_profit_pct else None
    else:
        stop_loss = current_price * (1 + Decimal(str(stop_loss_pct)) / 100) if stop_loss_pct else None
        take_profit = current_price * (1 - Decimal(str(take_profit_pct)) / 100) if take_profit_pct else None
    return stop_loss, take_profit


def _build_validation_report(config: dict) -> dict:
    """生成策略验证报告 — 校验指标是否可用"""
    from app.services.indicator_service import AVAILABLE_INDICATORS
    
    is_pipeline = any(k in config for k in ("alphas", "portfolio", "execution"))
    
    # 收集所有引用的指标
    indicators_used = set()
    
    if is_pipeline:
        for alpha in config.get("alphas", []):
            for cond in alpha.get("conditions", []):
                if "indicator" in cond:
                    indicators_used.add(cond["indicator"])
                if "reference" in cond:
                    indicators_used.add(cond["reference"])
    else:
        entry = config.get("entry", {})
        exit_block = config.get("exit", {})
        for cond in entry.get("conditions", []) + exit_block.get("conditions", []):
            if "indicator" in cond:
                indicators_used.add(cond["indicator"])
            if "reference" in cond:
                indicators_used.add(cond["reference"])
    
    # 校验指标白名单
    unknown = sorted(indicators_used - AVAILABLE_INDICATORS)
    
    report = {
        "is_valid": len(unknown) == 0,
        "is_pipeline": is_pipeline,
        "indicators_used": sorted(indicators_used),
    }
    
    if unknown:
        available_list = sorted(AVAILABLE_INDICATORS - {"price", "close", "near_support", "near_resistance"})
        report["unknown_indicators"] = unknown
        report["syntax_errors"] = [
            f"使用了不可用的指标: {', '.join(unknown)}。",
            f"可用指标: {', '.join(available_list)}",
        ]
    
    if is_pipeline:
        report["alphas"] = len(config.get("alphas", []))
        report["portfolio"] = config.get("portfolio", {}).get("type", "unknown")
    else:
        entry = config.get("entry", {})
        exit_block = config.get("exit", {})
        risk = config.get("risk", {})
        entry_conds = entry.get("conditions", [])
        exit_conds = exit_block.get("conditions", [])
        
        report["entry_conditions"] = len(entry_conds)
        report["exit_conditions"] = len(exit_conds)
        report["risk_summary"] = {
            "side": risk.get("side", "未设置"),
            "leverage": risk.get("leverage", "未设置"),
            "stop_loss_pct": risk.get("stop_loss_pct", "未设置"),
            "take_profit_pct": risk.get("take_profit_pct", "未设置"),
        }
        
        # 警告
        warnings = []
        if len(entry_conds) == 0:
            warnings.append("没有入场条件")
        if len(exit_conds) == 0:
            warnings.append("没有出场条件")
        if not risk.get("side"):
            warnings.append("未设置 risk.side (buy/sell)")
        if warnings:
            report["warnings"] = warnings
    
    return report


# ==================== 策略查询 ====================

@register_tool
async def list_strategies(
    db: AsyncSession,
    user_id: int,
) -> str:
    """列出所有可用策略 (用户创建的 + 预设模板)"""
    from app.services.quant.strategy import list_templates

    # 1. 用户自己的策略
    result = await db.execute(
        select(Strategy)
        .where(Strategy.user_id == user_id)
        .order_by(desc(Strategy.updated_at))
    )
    user_strategies = result.scalars().all()

    strategies = []
    for s in user_strategies:
        strategies.append({
            "id": s.id,
            "name": s.name,
            "symbol": s.symbol,
            "interval": s.interval,
            "is_active": s.is_active,
            "total_trades": s.total_trades,
            "win_trades": s.win_trades,
            "total_pnl": s.total_pnl,
            "last_signal": s.last_signal,
            "type": "user",
        })

    # 2. 预设模板
    templates = list_templates()
    for t in templates:
        strategies.append({
            "id": t["id"],
            "name": t["name"],
            "symbol": t["symbol"],
            "interval": t["interval"],
            "type": "template",
        })

    return json.dumps({
        "strategies": strategies,
        "user_count": len(user_strategies),
        "template_count": len(templates),
    }, ensure_ascii=False, default=str)


@register_tool
async def get_strategy_detail(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
) -> str:
    """查看策略详细配置 (支持用户策略 ID 或模板 ID)"""
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES

    engine = StrategyEngine()

    # 尝试作为数据库 ID 查询
    if str(strategy_id).isdigit():
        result = await db.execute(
            select(Strategy).where(
                Strategy.id == int(strategy_id),
                Strategy.user_id == user_id,
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy:
            try:
                config = engine.parse_yaml(strategy.config_yaml)
            except Exception:
                config = {}
            return json.dumps({
                "id": strategy.id,
                "name": strategy.name,
                "symbol": strategy.symbol,
                "interval": strategy.interval,
                "config_yaml": strategy.config_yaml,
                "config_parsed": config,
                "is_active": strategy.is_active,
                "total_trades": strategy.total_trades,
                "win_trades": strategy.win_trades,
                "total_pnl": strategy.total_pnl,
                "type": "user",
            }, ensure_ascii=False, default=str)

    # 尝试作为模板 ID 查询
    if strategy_id in STRATEGY_TEMPLATES:
        yaml_content = STRATEGY_TEMPLATES[strategy_id].strip()
        config = engine.parse_yaml(yaml_content)
        return json.dumps({
            "id": strategy_id,
            "name": config.get("name", strategy_id),
            "symbol": config.get("symbol", ""),
            "interval": config.get("interval", "1h"),
            "config_yaml": yaml_content,
            "config_parsed": config,
            "type": "template",
        }, ensure_ascii=False, default=str)

    return json.dumps({"error": f"找不到策略: {strategy_id}"}, ensure_ascii=False, default=str)


@register_tool
async def delete_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: int = 0,
) -> str:
    """删除指定策略"""
    if not strategy_id:
        return json.dumps({"error": "请提供 strategy_id"}, ensure_ascii=False, default=str)
    
    result = await db.execute(
        select(Strategy).where(Strategy.id == strategy_id, Strategy.user_id == user_id)
    )
    strategy = result.scalar_one_or_none()
    
    if not strategy:
        return json.dumps({"error": f"找不到策略 ID={strategy_id}，或该策略不属于你"}, ensure_ascii=False, default=str)
    
    name = strategy.name
    await db.delete(strategy)
    await db.commit()
    
    return json.dumps({
        "action": "deleted",
        "id": strategy_id,
        "name": name,
        "message": f"策略 '{name}' (ID: {strategy_id}) 已删除",
    }, ensure_ascii=False, default=str)


# ==================== 策略评估与执行 ====================

@register_tool
async def evaluate_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
    symbol: str = "",
) -> str:
    """
    评估策略在当前行情下的信号 (不会下单)

    参数:
        strategy_id: 用户策略 ID (数字) 或模板 ID (字符串)
        symbol: 可选, 覆盖策略默认的交易对
    """
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES

    engine = StrategyEngine()

    # 获取策略配置
    config = None
    strategy_name = strategy_id

    if str(strategy_id).isdigit():
        result = await db.execute(
            select(Strategy).where(
                Strategy.id == int(strategy_id),
                Strategy.user_id == user_id,
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy:
            config = engine.parse_yaml(strategy.config_yaml)
            strategy_name = strategy.name
    elif strategy_id in STRATEGY_TEMPLATES:
        config = engine.parse_yaml(STRATEGY_TEMPLATES[strategy_id].strip())
        strategy_name = config.get("name", strategy_id)

    if not config:
        return json.dumps({"error": f"找不到策略: {strategy_id}"}, ensure_ascii=False, default=str)

    # 如果指定了 symbol，覆盖策略默认的
    target_symbol = (symbol or config.get("symbol", "BTCUSDT")).upper()
    config["symbol"] = target_symbol

    # 获取多时间框架 K 线数据
    required_tfs = config.get("_required_timeframes", [config.get("interval", "1h")])
    
    try:
        klines_map = await _fetch_klines_map(target_symbol, required_tfs)
    except Exception as e:
        return json.dumps({"error": f"获取K线异常: {str(e)}"}, ensure_ascii=False, default=str)

    if not klines_map:
        return json.dumps({"error": "无法获取任何时间框架的K线数据"}, ensure_ascii=False, default=str)

    # 执行策略评估
    try:
        signal = engine.evaluate(config, klines_map=klines_map)
    except Exception as e:
        return json.dumps({"error": f"策略评估失败: {str(e)}"}, ensure_ascii=False, default=str)

    return json.dumps({
        "strategy_name": strategy_name,
        "symbol": target_symbol,
        "timeframes": required_tfs,
        "signal_type": signal.signal_type.value,
        "has_signal": signal.has_signal,
        "side": signal.side.value if signal.side else None,
        "confidence": round(signal.confidence, 2),
        "conditions_met": [str(c) for c in signal.conditions_met],
        "conditions_failed": [str(c) for c in signal.conditions_failed],
        "risk_config": signal.risk_config,
        "summary": signal.summary(),
    }, ensure_ascii=False, default=str)


@register_tool
async def run_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: str = "",
    symbol: str = "",
) -> str:
    """
    完整执行策略: 评估 → 风控 → 下单

    只有当策略产生入场信号 AND 通过风控时才下单。
    """
    from app.services.quant.strategy import StrategyEngine, STRATEGY_TEMPLATES
    from app.services.risk.risk_model import RiskModel
    from app.services.trading.position_manager import PositionManager
    from app.services.quant.indicators import get_indicator

    engine = StrategyEngine()
    risk_guard = RiskModel()

    # 获取策略配置
    config = None
    strategy_name = strategy_id

    if str(strategy_id).isdigit():
        result = await db.execute(
            select(Strategy).where(
                Strategy.id == int(strategy_id),
                Strategy.user_id == user_id,
            )
        )
        strategy = result.scalar_one_or_none()
        if strategy:
            config = engine.parse_yaml(strategy.config_yaml)
            strategy_name = strategy.name
    elif strategy_id in STRATEGY_TEMPLATES:
        config = engine.parse_yaml(STRATEGY_TEMPLATES[strategy_id].strip())
        strategy_name = config.get("name", strategy_id)

    if not config:
        return json.dumps({"error": f"找不到策略: {strategy_id}"}, ensure_ascii=False, default=str)

    target_symbol = (symbol or config.get("symbol", "BTCUSDT")).upper()
    config["symbol"] = target_symbol

    # 1. 获取多时间框架 K 线
    required_tfs = config.get("_required_timeframes", [config.get("interval", "1h")])
    try:
        klines_map = await _fetch_klines_map(target_symbol, required_tfs)
    except Exception as e:
        return json.dumps({"error": f"获取K线异常: {str(e)}"}, ensure_ascii=False, default=str)

    if not klines_map:
        return json.dumps({"error": "无法获取K线数据"}, ensure_ascii=False, default=str)

    # 取主时间框架 K 线 (用于价格和 ATR)
    default_interval = config.get("interval", "1h")
    main_klines = klines_map.get(default_interval, list(klines_map.values())[0])

    # 2. 策略评估
    try:
        signal = engine.evaluate(config, klines_map=klines_map)
    except Exception as e:
        return json.dumps({"error": f"策略评估异常: {str(e)}"}, ensure_ascii=False, default=str)

    if not signal.has_signal:
        return json.dumps({
            "action": "no_signal",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": f"策略 '{strategy_name}' 当前无交易信号",
            "conditions_met": [str(c) for c in signal.conditions_met],
            "conditions_failed": [str(c) for c in signal.conditions_failed],
        }, ensure_ascii=False, default=str)

    if signal.signal_type.value == "exit":
        return json.dumps({
            "action": "exit_signal",
            "strategy_name": strategy_name,
            "symbol": target_symbol,
            "message": f"策略 '{strategy_name}' 建议平仓",
            "side": signal.side.value if signal.side else None,
            "conditions_met": [str(c) for c in signal.conditions_met],
        }, ensure_ascii=False, default=str)

    # 3. 获取钱包余额和持仓 (供 Pipeline 风控使用)
    wallet_result = await db.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = wallet_result.scalar_one_or_none()
    wallet_balance = float(wallet.balance) if wallet else 0.0

    if wallet_balance <= 0:
        return json.dumps({"error": "钱包余额不足"}, ensure_ascii=False, default=str)

    pos_result = await db.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
    )
    open_positions = [
        {"symbol": p.symbol, "side": p.side.value, "size": float(p.size), "margin": float(p.margin)}
        for p in pos_result.scalars().all()
    ]

    # 4. 计算下单参数
    risk_config = signal.risk_config
    current_price = Decimal(str(main_klines[-1]["close"]))
    leverage = risk_config.get("leverage", 1)
    position_pct = risk_config.get("position_pct", 10)

    # L4: 波动率自适应仓位
    if risk_config.get("volatility_adjust"):
        try:
            atr_val = get_indicator("atr", main_klines)
            if atr_val and float(current_price) > 0:
                atr_pct = atr_val / float(current_price) * 100
                vol_factor = max(0.33, min(1.0, 1.0 / atr_pct))
                original_pct = position_pct
                position_pct = round(position_pct * vol_factor, 1)
                logger.info(
                    f"[Strategy] 波动率调整: ATR%={atr_pct:.2f}%, "
                    f"仓位 {original_pct}% → {position_pct}%"
                )
        except Exception as e:
            logger.warning(f"[Strategy] 波动率调整失败: {e}")

    trade_amount = wallet_balance * position_pct / 100
    quantity = Decimal(str(round(trade_amount / float(current_price), 4)))

    side_map = {"buy": PositionSide.LONG, "sell": PositionSide.SHORT}
    position_side = side_map.get(signal.side.value, PositionSide.LONG) if signal.side else PositionSide.LONG

    # 计算止损止盈 (L2: 支持动态止损)
    stop_type = risk_config.get("stop_type", "fixed")
    stop_loss_pct = risk_config.get("stop_loss_pct", 3)
    take_profit_pct = risk_config.get("take_profit_pct", 9)

    if stop_type == "atr":
        try:
            atr_val = get_indicator("atr", main_klines)
            multiplier = risk_config.get("atr_stop_multiplier", 2)
            if atr_val:
                atr_stop_distance = Decimal(str(atr_val * multiplier))
                if position_side == PositionSide.LONG:
                    stop_loss = current_price - atr_stop_distance
                    take_profit = current_price + atr_stop_distance * Decimal("3") if take_profit_pct else None
                else:
                    stop_loss = current_price + atr_stop_distance
                    take_profit = current_price - atr_stop_distance * Decimal("3") if take_profit_pct else None
            else:
                stop_loss, take_profit = _calc_fixed_stops(
                    current_price, position_side, stop_loss_pct, take_profit_pct
                )
        except Exception:
            stop_loss, take_profit = _calc_fixed_stops(
                current_price, position_side, stop_loss_pct, take_profit_pct
            )
    elif stop_type == "trailing":
        trailing_pct = risk_config.get("trailing_pct", 1.5)
        stop_loss, take_profit = _calc_fixed_stops(
            current_price, position_side, trailing_pct, take_profit_pct
        )
    else:
        stop_loss, take_profit = _calc_fixed_stops(
            current_price, position_side, stop_loss_pct, take_profit_pct
        )

    # 5. 通过 Pipeline 统一下单 (Risk → Execution)
    try:
        from app.core.pipeline import get_pipeline
        
        source = agent_source_var.get()
        pipeline = get_pipeline(user_id)
        
        order_side = "buy" if position_side == PositionSide.LONG else "sell"
        
        result = await pipeline.submit_from_signal(
            db=db,
            symbol=target_symbol,
            side=order_side,
            quantity=quantity,
            leverage=leverage,
            price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=source,
            strategy_name=strategy_name,
            available_balance=Decimal(str(wallet_balance)),
            total_equity=Decimal(str(wallet.total_equity)) if wallet else Decimal("0"),
            open_positions=open_positions,
        )
        
        if result.get("success"):
            # 递增策略交易计数
            if str(strategy_id).isdigit() and strategy:
                strategy.total_trades += 1
                strategy.last_run_at = utc_now()
            await db.commit()
            return json.dumps({
                "action": "executed",
                "strategy_name": strategy_name,
                "symbol": target_symbol,
                "side": position_side.value,
                "quantity": str(quantity),
                "entry_price": str(current_price),
                "leverage": leverage,
                "stop_loss": str(stop_loss) if stop_loss else None,
                "stop_type": stop_type,
                "take_profit": str(take_profit) if take_profit else None,
                "position_pct_actual": position_pct,
                "order_id": result.get("order_id"),
                "message": f"策略 '{strategy_name}' 已通过 Pipeline 执行",
            }, ensure_ascii=False, default=str)
        else:
            return json.dumps({
                "action": "risk_blocked",
                "strategy_name": strategy_name,
                "symbol": target_symbol,
                "message": result.get("error", "Pipeline 执行失败"),
                "signal": signal.summary(),
            }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"下单失败: {str(e)}"}, ensure_ascii=False, default=str)


# ==================== 策略创建与更新 ====================

@register_tool
async def create_strategy(
    db: AsyncSession,
    user_id: int,
    name: str = "",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    config_yaml: str = "",
) -> str:
    """
    创建新策略并保存到数据库

    参数:
        name: 策略名称
        symbol: 交易对
        interval: K 线周期
        config_yaml: YAML 格式的策略配置
    """
    from app.services.quant.strategy import StrategyEngine

    if not name or not config_yaml:
        return json.dumps({"error": "缺少必要参数: name 和 config_yaml"}, ensure_ascii=False, default=str)

    engine = StrategyEngine()
    try:
        config = engine.parse_yaml(config_yaml)
    except ValueError as e:
        return json.dumps({"error": f"YAML 配置验证失败: {str(e)}"}, ensure_ascii=False, default=str)

    # 强校验：是否存在不支持的指标
    report = _build_validation_report(config)
    if not report.get("is_valid", False):
        error_msgs = []
        if report.get("unknown_indicators"):
            error_msgs.append(f"使用了系统不支持的指标: {', '.join(report['unknown_indicators'])}")
        if report.get("syntax_errors"):
            error_msgs.extend(report["syntax_errors"])
        if error_msgs:
            return json.dumps({"error": f"策略配置无效: {'; '.join(error_msgs)}"}, ensure_ascii=False, default=str)

    strategy = Strategy(
        user_id=user_id,
        name=name,
        symbol=symbol.upper(),
        interval=interval,
        config_yaml=config_yaml,
        is_active=False,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)

    return json.dumps({
        "action": "created",
        "id": strategy.id,
        "name": strategy.name,
        "symbol": strategy.symbol,
        "interval": strategy.interval,
        "message": f"策略 '{name}' 已创建 (ID: {strategy.id})，默认未启用",
        "validation_report": report,
    }, ensure_ascii=False, default=str)


@register_tool
async def update_strategy(
    db: AsyncSession,
    user_id: int,
    strategy_id: int = 0,
    config_yaml: str = "",
    name: str = "",
    symbol: str = "",
    interval: str = "",
) -> str:
    """
    安全更新策略 (带 YAML 验证 + 干跑评估)

    在保存前验证:
    1. YAML 语法和结构是否正确
    2. 使用的指标是否全部受支持
    3. 干跑评估是否能正常执行 (不下单)

    参数:
        strategy_id: 策略 ID
        config_yaml: 新的 YAML 配置 (可选, 不传则不修改配置)
        name: 新的策略名称 (可选)
        interval: 新的 K 线周期 (可选)
    """
    from app.services.quant.strategy import StrategyEngine

    if not strategy_id:
        return json.dumps({"error": "缺少 strategy_id"}, ensure_ascii=False, default=str)

    result = await db.execute(
        select(Strategy).where(
            Strategy.id == int(strategy_id),
            Strategy.user_id == user_id,
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        return json.dumps({"error": f"找不到策略 ID={strategy_id}"}, ensure_ascii=False, default=str)

    # 保存旧配置用于回滚
    old_yaml = strategy.config_yaml
    old_name = strategy.name
    old_interval = strategy.interval

    engine = StrategyEngine()

    # 如果提供了新 YAML, 验证它
    if config_yaml:
        # Step 1: 解析 YAML
        try:
            config = engine.parse_yaml(config_yaml)
        except ValueError as e:
            return json.dumps({
                "error": f"YAML 解析失败: {str(e)}",
                "hint": "请检查 YAML 语法是否正确",
            }, ensure_ascii=False, default=str)

        # Step 2: 验证指标和结构
        report = _build_validation_report(config)
        if not report.get("is_valid", False):
            error_msgs = []
            if report.get("unknown_indicators"):
                error_msgs.append(f"不支持的指标: {', '.join(report['unknown_indicators'])}")
            if report.get("syntax_errors"):
                error_msgs.extend(report["syntax_errors"])
            return json.dumps({
                "error": f"策略配置无效: {'; '.join(error_msgs)}",
                "old_config_preserved": True,
            }, ensure_ascii=False, default=str)

        # Step 3: 干跑评估 — 确保策略能正常运行
        try:
            target_symbol = config.get("symbol", strategy.symbol)
            required_tfs = config.get("_required_timeframes", [config.get("interval", strategy.interval)])
            klines_map = await _fetch_klines_map(target_symbol, required_tfs)
            if klines_map:
                engine.evaluate(config, klines_map=klines_map)
        except Exception as e:
            return json.dumps({
                "error": f"干跑评估失败 (策略无法运行): {str(e)}",
                "old_config_preserved": True,
                "hint": "请检查 entry/exit 条件中的指标名称和参数是否正确",
            }, ensure_ascii=False, default=str)

        # 所有验证通过, 更新配置
        strategy.config_yaml = config_yaml

    # 更新其他字段
    if name:
        strategy.name = name
    if symbol:
        strategy.symbol = symbol.upper()
    if interval:
        strategy.interval = interval

    await db.commit()
    await db.refresh(strategy)

    changes = []
    if config_yaml:
        changes.append("配置已更新")
    if name:
        changes.append(f"名称→{name}")
    if symbol:
        changes.append(f"交易对→{symbol.upper()}")
    if interval:
        changes.append(f"周期→{interval}")

    return json.dumps({
        "action": "updated",
        "id": strategy.id,
        "name": strategy.name,
        "changes": changes,
        "message": f"策略 '{strategy.name}' (ID:{strategy.id}) 更新成功: {', '.join(changes)}",
    }, ensure_ascii=False, default=str)


# ==================== 模块与流水线 ====================

@register_tool
async def list_modules(
    db: AsyncSession,
    user_id: int,
    layer: str = "",
) -> str:
    """
    查询可用的策略模块目录

    参数:
        layer: 指定层 (alpha/portfolio/risk/execution)，空=显示全部

    返回:
        各层可用模块清单，含参数说明
    """
    from app.services.quant.module_registry import list_modules as _list, get_registry_summary

    if layer and layer not in ("alpha", "portfolio", "risk", "execution"):
        return json.dumps({"error": f"未知层: {layer}。可选: alpha/portfolio/risk/execution"}, ensure_ascii=False, default=str)

    modules = _list(layer or None)

    if not modules:
        return json.dumps({"error": f"层 '{layer}' 没有可用模块"}, ensure_ascii=False, default=str)

    result = []
    for m in modules:
        result.append(m.to_dict())

    summary = get_registry_summary()

    return json.dumps({
        "modules": result,
        "summary": summary,
        "hint": "使用 create_pipeline_strategy 时，从每层选择一个模块并配置参数",
    }, ensure_ascii=False, indent=2)


@register_tool
async def create_pipeline_strategy(
    db: AsyncSession,
    user_id: int,
    name: str = "",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    config_yaml: str = "",
) -> str:
    """
    创建多模块流水线策略并保存到数据库

    参数:
        name: 策略名称
        symbol: 交易对
        interval: K 线周期
        config_yaml: YAML 格式的 pipeline 策略配置
    """
    from app.services.quant.strategy import StrategyEngine

    if not name or not config_yaml:
        return json.dumps({"error": "缺少必要参数: name 和 config_yaml"}, ensure_ascii=False, default=str)

    engine = StrategyEngine()
    try:
        config = engine.parse_yaml(config_yaml)
    except ValueError as e:
        return json.dumps({"error": f"YAML 配置验证失败: {str(e)}"}, ensure_ascii=False, default=str)

    report = _build_validation_report(config)

    strategy = Strategy(
        user_id=user_id,
        name=name,
        symbol=symbol.upper(),
        interval=interval,
        config_yaml=config_yaml,
        strategy_type="pipeline",
        is_active=False,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)

    return json.dumps({
        "action": "created",
        "id": strategy.id,
        "name": strategy.name,
        "symbol": strategy.symbol,
        "interval": strategy.interval,
        "message": f"流水线策略 '{name}' 已创建 (ID: {strategy.id})，默认未启用",
        "validation_report": report,
    }, ensure_ascii=False, default=str)
