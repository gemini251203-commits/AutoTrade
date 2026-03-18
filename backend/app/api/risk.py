"""
Risk API
=========
风控端点

端点:
    GET  /api/risk/positions    - 获取仓位风险数据 (带实时盈亏)
    GET  /api/risk/account      - 获取账户风险汇总
    POST /api/risk/check        - 手动触发风控检查
"""

from decimal import Decimal
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from loguru import logger

from app.api.deps import DbSession, CurrentUser
from app.services.risk import RiskEngine, PositionRisk, AccountRisk
from app.models.position import PositionSide


router = APIRouter(tags=["Risk"])


# ==================== Schemas ====================

class PositionRiskResponse(BaseModel):
    """仓位风险响应"""
    position_id: int
    symbol: str
    side: str
    size: str
    entry_price: str
    mark_price: str
    leverage: int
    margin: str
    margin_mode: str  # 'cross' or 'isolated'
    liquidation_price: Optional[str]
    is_dynamic_liq: bool  # True if cross margin (dynamic liq price)
    unrealized_pnl: str
    roe_percent: str
    margin_ratio: str
    is_at_risk: bool
    should_liquidate: bool
    # 🔥 新增止盈止损字段
    stop_loss: Optional[str] = None
    take_profit: Optional[str] = None
    source: str = "manual"


class AccountRiskResponse(BaseModel):
    """账户风险响应"""
    user_id: int
    total_margin: str
    total_unrealized_pnl: str
    total_equity: str
    margin_ratio: str
    positions_at_risk: int
    positions_to_liquidate: int


class RiskCheckResponse(BaseModel):
    """风控检查响应"""
    checked: int
    liquidated: int
    details: List[str]


# ==================== Helper ====================

async def get_current_prices(symbols: List[str]) -> Dict[str, Decimal]:
    """
    获取当前市场价格
    
    TODO: 从 Redis 缓存或交易所 API 获取实时价格
    目前使用模拟价格
    """
    import httpx
    
    price_map = {}
    
    for symbol in symbols:
        try:
            # 从 Binance API 获取最新价格
            async with httpx.AsyncClient() as client:
                url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
                resp = await client.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    price_map[symbol] = Decimal(data.get("price", "0"))
        except Exception as e:
            logger.warning(f"[Risk API] Failed to get price for {symbol}: {e}")
    
    return price_map


def risk_to_response(risk: PositionRisk) -> PositionRiskResponse:
    """转换 PositionRisk 为 API 响应"""
    # 判断是否全仓模式
    margin_mode = getattr(risk, 'margin_mode', 'cross')
    is_dynamic = margin_mode == 'cross'
    
    return PositionRiskResponse(
        position_id=risk.position_id,
        symbol=risk.symbol,
        side=risk.side.value,
        size=str(risk.size),
        entry_price=str(risk.entry_price),
        mark_price=str(risk.mark_price),
        leverage=risk.leverage,
        margin=str(risk.margin),
        margin_mode=margin_mode,
        liquidation_price=str(risk.liquidation_price) if risk.liquidation_price else None,
        is_dynamic_liq=is_dynamic,
        unrealized_pnl=str(risk.unrealized_pnl.quantize(Decimal("0.01"))),
        roe_percent=str(risk.roe_percent.quantize(Decimal("0.01"))),
        margin_ratio=str(risk.margin_ratio.quantize(Decimal("0.0001"))),
        is_at_risk=risk.is_at_risk,
        should_liquidate=risk.should_liquidate,
        # 🔥 填充止盈止损
        stop_loss=str(risk.stop_loss) if risk.stop_loss else None,
        take_profit=str(risk.take_profit) if risk.take_profit else None,
        source=risk.source,
    )


# ==================== Routes ====================

@router.get("/positions", response_model=List[PositionRiskResponse])
async def get_positions_risk(
    current_user: CurrentUser,
    db: DbSession,
    symbol: Optional[str] = None,
):
    """
    获取用户仓位风险数据
    
    返回每个仓位的:
    - 未实现盈亏 (unrealized_pnl)
    - 收益率 (roe_percent)
    - 保证金率 (margin_ratio)
    - 是否接近强平 (is_at_risk)
    """
    from app.services.trading import PositionManager
    from app.models.position import PositionStatus
    
    # 获取用户仓位
    positions = await PositionManager.get_user_positions(
        db, current_user.id, PositionStatus.OPEN
    )
    
    if not positions:
        return []
    
    # 获取需要的交易对价格
    symbols = list(set(p.symbol for p in positions))
    price_map = await get_current_prices(symbols)
    
    # 计算每个仓位的风险
    risks = await RiskEngine.get_positions_risk(db, current_user.id, price_map)
    
    # 可选符号过滤
    if symbol:
        risks = [r for r in risks if r.symbol == symbol]
    
    return [risk_to_response(r) for r in risks]


@router.get("/account", response_model=AccountRiskResponse)
async def get_account_risk(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    获取账户整体风险汇总
    
    返回:
    - 总保证金
    - 总未实现盈亏
    - 总权益
    - 账户保证金率
    - 高风险仓位数量
    """
    from app.services.trading import PositionManager
    from app.models.position import PositionStatus
    
    # 获取用户仓位
    positions = await PositionManager.get_user_positions(
        db, current_user.id, PositionStatus.OPEN
    )
    
    if not positions:
        return AccountRiskResponse(
            user_id=current_user.id,
            total_margin="0",
            total_unrealized_pnl="0",
            total_equity="0",
            margin_ratio="0",
            positions_at_risk=0,
            positions_to_liquidate=0,
        )
    
    # 获取价格
    symbols = list(set(p.symbol for p in positions))
    price_map = await get_current_prices(symbols)
    
    # 计算账户风险
    account = await RiskEngine.calculate_account_risk(db, current_user.id, price_map)
    
    return AccountRiskResponse(
        user_id=account.user_id,
        total_margin=str(account.total_margin.quantize(Decimal("0.01"))),
        total_unrealized_pnl=str(account.total_unrealized_pnl.quantize(Decimal("0.01"))),
        total_equity=str(account.total_equity.quantize(Decimal("0.01"))),
        margin_ratio=str(account.margin_ratio.quantize(Decimal("0.0001"))),
        positions_at_risk=account.positions_at_risk,
        positions_to_liquidate=account.positions_to_liquidate,
    )


@router.post("/check", response_model=RiskCheckResponse)
async def trigger_risk_check(
    current_user: CurrentUser,
    db: DbSession,
):
    """
    手动触发风控检查
    
    检查所有仓位是否触发强平，并执行强平操作
    
    ⚠️ 此端点仅用于测试/管理，生产环境应由后台任务自动执行
    """
    from app.services.trading import PositionManager
    from app.models.position import PositionStatus
    
    # 获取用户仓位
    positions = await PositionManager.get_user_positions(
        db, current_user.id, PositionStatus.OPEN
    )
    
    if not positions:
        return RiskCheckResponse(checked=0, liquidated=0, details=[])
    
    # 获取价格
    symbols = list(set(p.symbol for p in positions))
    price_map = await get_current_prices(symbols)
    
    # 执行风控检查
    details = []
    liquidated_count = 0
    
    for position in positions:
        mark_price = price_map.get(position.symbol)
        if not mark_price:
            continue
        
        risk = RiskEngine.calculate_position_risk(position, mark_price)
        
        if risk.should_liquidate:
            await RiskEngine.execute_liquidation(db, position.id)
            await db.commit()
            liquidated_count += 1
            details.append(
                f"Liquidated: {position.symbol} {position.side.value} "
                f"@ {mark_price} (liq={position.liquidation_price})"
            )
        elif risk.is_at_risk:
            details.append(
                f"At risk: {position.symbol} {position.side.value} "
                f"margin_ratio={risk.margin_ratio:.4f}"
            )
    
    return RiskCheckResponse(
        checked=len(positions),
        liquidated=liquidated_count,
        details=details,
    )
