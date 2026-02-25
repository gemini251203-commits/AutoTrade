"""
Trend Analysis API
==================
趋势分析方案 CRUD + 手动触发分析
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.api.deps import get_current_user, CurrentUser
from app.models.trend_scheme import TrendScheme, TrendSnapshot
from app.services.quant.trend_analyzer import TrendAnalyzer, PRESET_SCHEMES

router = APIRouter()


# ==================== Schemas ====================


class TrendSchemeCreate(BaseModel):
    name: str
    config_yaml: str
    is_active: bool = True


class TrendSchemeUpdate(BaseModel):
    name: Optional[str] = None
    config_yaml: Optional[str] = None
    is_active: Optional[bool] = None


class TrendSchemeResponse(BaseModel):
    id: int
    name: str
    config_yaml: str
    is_active: bool
    is_preset: bool
    last_result: Optional[dict] = None
    last_run_at: Optional[str] = None
    created_at: str


class TrendSnapshotResponse(BaseModel):
    id: int
    scheme_id: int
    symbol: str
    direction: str
    direction_score: float
    strength: str
    strength_score: float
    volatility: str
    momentum: str
    regime: str
    confidence: float
    suitable_strategies: Optional[list] = None
    created_at: str


# ==================== Endpoints ====================


@router.get("/schemes", response_model=List[TrendSchemeResponse])
async def list_schemes(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """列出用户的所有趋势分析方�?""
    result = await db.execute(
        select(TrendScheme).where(
            TrendScheme.user_id == current_user.id,
        ).order_by(TrendScheme.created_at.desc())
    )
    schemes = result.scalars().all()

    return [
        TrendSchemeResponse(
            id=s.id,
            name=s.name,
            config_yaml=s.config_yaml,
            is_active=s.is_active,
            is_preset=s.is_preset,
            last_result=s.last_result,
            last_run_at=s.last_run_at.isoformat() + "Z" if s.last_run_at else None,
            created_at=s.created_at.isoformat() + "Z",
        )
        for s in schemes
    ]


@router.post("/schemes")
async def create_scheme(
    body: TrendSchemeCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """创建新的趋势分析方案"""
    # 验证 YAML
    analyzer = TrendAnalyzer()
    try:
        analyzer.parse_yaml(body.config_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    scheme = TrendScheme(
        user_id=current_user.id,
        name=body.name,
        config_yaml=body.config_yaml,
        is_active=body.is_active,
    )
    db.add(scheme)
    await db.commit()
    await db.refresh(scheme)

    return {"id": scheme.id, "name": scheme.name, "message": f"方案 '{scheme.name}' 已创�?}


@router.put("/schemes/{scheme_id}")
async def update_scheme(
    scheme_id: int,
    body: TrendSchemeUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """修改趋势分析方案"""
    result = await db.execute(
        select(TrendScheme).where(
            TrendScheme.id == scheme_id,
            TrendScheme.user_id == current_user.id,
        )
    )
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=404, detail="方案不存�?)

    if body.name is not None:
        scheme.name = body.name
    if body.config_yaml is not None:
        # 验证 YAML
        analyzer = TrendAnalyzer()
        try:
            analyzer.parse_yaml(body.config_yaml)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        scheme.config_yaml = body.config_yaml
    if body.is_active is not None:
        scheme.is_active = body.is_active

    await db.commit()
    return {"id": scheme.id, "message": f"方案 '{scheme.name}' 已更�?}


@router.delete("/schemes/{scheme_id}")
async def delete_scheme(
    scheme_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """删除趋势分析方案"""
    result = await db.execute(
        select(TrendScheme).where(
            TrendScheme.id == scheme_id,
            TrendScheme.user_id == current_user.id,
        )
    )
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=404, detail="方案不存�?)

    await db.delete(scheme)
    await db.commit()
    return {"message": f"方案 '{scheme.name}' 已删�?}


@router.post("/schemes/{scheme_id}/run")
async def run_analysis(
    scheme_id: int,
    current_user: CurrentUser,
    symbol: str = "BTCUSDT",
    db: AsyncSession = Depends(get_db),
):
    """手动触发趋势分析"""
    result = await db.execute(
        select(TrendScheme).where(
            TrendScheme.id == scheme_id,
            TrendScheme.user_id == current_user.id,
        )
    )
    scheme = result.scalar_one_or_none()
    if not scheme:
        raise HTTPException(status_code=404, detail="方案不存�?)

    # 获取 K �?
    from app.core.network import net_manager
    interval = "1h"
    try:
        analyzer = TrendAnalyzer()
        config = analyzer.parse_yaml(scheme.config_yaml)
        interval = config.get("interval", "1h")
    except Exception:
        pass

    try:
        async with net_manager.get_client(timeout=15.0) as client:
            resp = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={"symbol": symbol.upper(), "interval": interval, "limit": 200},
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="获取 K 线失�?)

            raw = resp.json()
            klines = [{
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            } for k in raw]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取行情失败: {e}")

    # 执行分析
    analyzer = TrendAnalyzer()
    config = analyzer.parse_yaml(scheme.config_yaml)
    trend_result = analyzer.analyze(config, klines, symbol=symbol.upper())

    # 保存结果
    scheme.last_result = trend_result.to_dict()
    scheme.last_run_at = datetime.utcnow()

    snapshot = TrendSnapshot(
        scheme_id=scheme.id,
        user_id=current_user.id,
        symbol=symbol.upper(),
        direction=trend_result.direction,
        direction_score=trend_result.direction_score,
        strength=trend_result.strength,
        strength_score=trend_result.strength_score,
        volatility=trend_result.volatility,
        momentum=trend_result.momentum,
        regime=trend_result.regime,
        confidence=trend_result.confidence,
        suitable_strategies=trend_result.suitable_strategies,
        result_json=trend_result.to_dict(),
    )
    db.add(snapshot)
    await db.commit()

    return trend_result.to_dict()


@router.get("/snapshots")
async def list_snapshots(
    current_user: CurrentUser,
    scheme_id: Optional[int] = None,
    symbol: Optional[str] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """查看趋势分析历史快照"""
    query = select(TrendSnapshot).where(
        TrendSnapshot.user_id == current_user.id,
    )
    if scheme_id:
        query = query.where(TrendSnapshot.scheme_id == scheme_id)
    if symbol:
        query = query.where(TrendSnapshot.symbol == symbol.upper())
    query = query.order_by(TrendSnapshot.created_at.desc()).limit(limit)

    result = await db.execute(query)
    snapshots = result.scalars().all()

    return [
        TrendSnapshotResponse(
            id=s.id,
            scheme_id=s.scheme_id,
            symbol=s.symbol,
            direction=s.direction,
            direction_score=s.direction_score,
            strength=s.strength,
            strength_score=s.strength_score,
            volatility=s.volatility,
            momentum=s.momentum,
            regime=s.regime,
            confidence=s.confidence,
            suitable_strategies=s.suitable_strategies,
            created_at=s.created_at.isoformat() + "Z",
        )
        for s in snapshots
    ]


@router.post("/init-presets")
async def init_presets(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """初始化预置方�?(用户首次使用时调�?"""
    # 检查是否已有预置方�?
    existing = await db.execute(
        select(TrendScheme).where(
            TrendScheme.user_id == current_user.id,
            TrendScheme.is_preset == True,
        )
    )
    if existing.scalars().first():
        return {"message": "预置方案已存�?}

    created = []
    for key, preset in PRESET_SCHEMES.items():
        scheme = TrendScheme(
            user_id=current_user.id,
            name=preset["name"],
            config_yaml=preset["yaml"],
            is_active=(key == "standard"),  # 只激活标准方�?
            is_preset=True,
        )
        db.add(scheme)
        created.append(preset["name"])

    await db.commit()
    return {"message": f"已创�?{len(created)} 个预置方�?, "schemes": created}
