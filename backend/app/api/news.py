"""
News API
================
新闻模块端点

端点:
    GET    /api/news/articles          - 新闻列表
    GET    /api/news/sentiment/{curr}  - 市场情绪
    GET    /api/news/alerts            - 监控规则列表
    POST   /api/news/alerts            - 创建监控规则
    PUT    /api/news/alerts/{id}       - 更新监控规则
    DELETE /api/news/alerts/{id}       - 删除监控规则
    GET    /api/news/thinkings         - AI思考记录
    GET    /api/news/stats             - 新闻交易绩效
"""

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from app.api.deps import CurrentUser, DbSession
from app.models.news import NewsArticle, NewsAlert, NewsThinking
from app.services.news.service import (
    get_latest_news,
    get_market_sentiment,
    get_user_alerts,
    get_news_trading_stats,
    get_thinkings,
    _alert_to_dict,
)


router = APIRouter(tags=["News"])


# ==================== Schemas ====================

class NewsArticleResponse(BaseModel):
    """新闻响应"""
    id: int
    source: str
    title: str
    title_zh: Optional[str] = None
    url: str
    currencies: Optional[list] = None
    news_category: Optional[str] = None
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    importance: Optional[str] = None
    votes_positive: Optional[int] = None
    votes_negative: Optional[int] = None
    published_at: str
    created_at: str


class SentimentResponse(BaseModel):
    """市场情绪响应"""
    overall: str
    score: float
    total_articles: int
    positive_count: int
    negative_count: int
    neutral_count: int
    by_category: dict
    hours: int
    currency: Optional[str] = None


class CreateAlertRequest(BaseModel):
    """创建监控规则"""
    name: str = Field(..., max_length=100, example="美联储降息做多")
    keywords: list = Field(..., example=["降息", "rate cut"])
    news_categories: Optional[list] = Field(default=None, example=["macro"])
    currencies: Optional[list] = Field(default=None, example=["BTC"])
    sentiment_filter: str = Field(default="any", example="any")
    action: str = Field(default="notify", example="trade")
    trade_side: Optional[str] = Field(default=None, example="buy")
    trade_symbol: Optional[str] = Field(default=None, example="BTCUSDT")
    trade_position_pct: Optional[float] = Field(default=None, le=15, example=10)
    trade_leverage: Optional[int] = Field(default=None, le=20, example=5)
    trade_stop_loss_pct: Optional[float] = Field(default=None, example=3)
    trade_take_profit_pct: Optional[float] = Field(default=None, example=9)


class UpdateAlertRequest(BaseModel):
    """更新监控规则"""
    name: Optional[str] = None
    keywords: Optional[list] = None
    news_categories: Optional[list] = None
    currencies: Optional[list] = None
    sentiment_filter: Optional[str] = None
    action: Optional[str] = None
    trade_side: Optional[str] = None
    trade_symbol: Optional[str] = None
    trade_position_pct: Optional[float] = Field(default=None, le=15)
    trade_leverage: Optional[int] = Field(default=None, le=20)
    trade_stop_loss_pct: Optional[float] = None
    trade_take_profit_pct: Optional[float] = None
    is_active: Optional[bool] = None
    is_reliable: Optional[bool] = None
    reliability_note: Optional[str] = None


class AlertResponse(BaseModel):
    """监控规则响应"""
    id: int
    user_id: int
    name: str
    keywords: list
    news_categories: Optional[list] = None
    currencies: Optional[list] = None
    sentiment_filter: str
    action: str
    trade_side: Optional[str] = None
    trade_symbol: Optional[str] = None
    trade_position_pct: Optional[float] = None
    trade_leverage: Optional[int] = None
    trade_stop_loss_pct: Optional[float] = None
    trade_take_profit_pct: Optional[float] = None
    is_active: bool
    is_reliable: bool
    reliability_note: Optional[str] = None
    triggered_count: int
    win_count: int
    loss_count: int
    total_pnl: float
    win_rate: float
    last_triggered_at: Optional[str] = None
    created_at: str


class ThinkingResponse(BaseModel):
    """AI思考记录响应"""
    id: int
    user_id: int
    news_article_id: int
    news_alert_id: Optional[int] = None
    step_get_news: Optional[str] = None
    step_analyze: Optional[str] = None
    step_evaluate: Optional[str] = None
    step_decide: Optional[str] = None
    decision: str
    trade_action: Optional[dict] = None
    position_id: Optional[int] = None
    trade_result: Optional[str] = None
    trade_pnl: Optional[float] = None
    ai_reflection: Optional[str] = None
    created_at: str


class TradingStatsResponse(BaseModel):
    """新闻交易绩效响应"""
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl: float


# ==================== Routes ====================

@router.get("/articles", response_model=List[NewsArticleResponse])
async def list_articles(
    current_user: CurrentUser,
    db: DbSession,
    currency: Optional[str] = Query(default=None, example="BTC"),
    news_category: Optional[str] = Query(default=None, example="macro"),
    keyword: Optional[str] = Query(default=None, example="ETF"),
    limit: int = Query(default=20, le=100),
):
    """获取最新新闻列表"""
    return await get_latest_news(
        db,
        currency=currency,
        news_category=news_category,
        keyword=keyword,
        limit=limit,
    )


@router.get("/sentiment/{currency}", response_model=SentimentResponse)
async def get_sentiment(
    currency: str,
    current_user: CurrentUser,
    db: DbSession,
    hours: int = Query(default=24, le=168),
):
    """获取指定币种的市场情绪"""
    return await get_market_sentiment(db, currency=currency, hours=hours)


@router.get("/alerts", response_model=List[AlertResponse])
async def list_alerts(
    current_user: CurrentUser,
    db: DbSession,
):
    """获取用户的所有监控规则"""
    return await get_user_alerts(db, user_id=current_user.id)


@router.post("/alerts", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    request: CreateAlertRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """创建新闻监控规则"""
    # 验证: trade 模式必须有交易参数
    if request.action == "trade":
        if not request.trade_side:
            raise HTTPException(
                status_code=400,
                detail="交易模式需要指定 trade_side (buy/sell)",
            )
        if not request.trade_symbol:
            raise HTTPException(
                status_code=400,
                detail="交易模式需要指定 trade_symbol (如 BTCUSDT)",
            )
    
    # 限制规则数量
    existing = await get_user_alerts(db, user_id=current_user.id)
    if len(existing) >= 20:
        raise HTTPException(
            status_code=400,
            detail="监控规则已达上限 (20条)",
        )
    
    alert = NewsAlert(
        user_id=current_user.id,
        name=request.name,
        keywords=request.keywords,
        news_categories=request.news_categories,
        currencies=request.currencies,
        sentiment_filter=request.sentiment_filter,
        action=request.action,
        trade_side=request.trade_side,
        trade_symbol=request.trade_symbol,
        trade_position_pct=request.trade_position_pct,
        trade_leverage=request.trade_leverage,
        trade_stop_loss_pct=request.trade_stop_loss_pct,
        trade_take_profit_pct=request.trade_take_profit_pct,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    
    return _alert_to_dict(alert)


@router.put("/alerts/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: int,
    request: UpdateAlertRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    """更新监控规则 (含可靠性开关)"""
    result = await db.execute(
        select(NewsAlert).where(
            NewsAlert.id == alert_id,
            NewsAlert.user_id == current_user.id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="监控规则不存在")
    
    # 逐字段更新 (只更新传入的字段)
    update_fields = request.model_dump(exclude_unset=True)
    for field_name, value in update_fields.items():
        setattr(alert, field_name, value)
    
    await db.commit()
    await db.refresh(alert)
    
    return _alert_to_dict(alert)


@router.delete("/alerts/{alert_id}")
async def delete_alert(
    alert_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """删除监控规则"""
    result = await db.execute(
        select(NewsAlert).where(
            NewsAlert.id == alert_id,
            NewsAlert.user_id == current_user.id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="监控规则不存在")
    
    await db.delete(alert)
    await db.commit()
    
    return {"message": f"监控规则 '{alert.name}' 已删除"}


@router.get("/thinkings", response_model=List[ThinkingResponse])
async def list_thinkings(
    current_user: CurrentUser,
    db: DbSession,
    news_article_id: Optional[int] = Query(default=None),
    limit: int = Query(default=20, le=100),
):
    """获取AI新闻思考记录"""
    return await get_thinkings(
        db,
        user_id=current_user.id,
        news_article_id=news_article_id,
        limit=limit,
    )


@router.get("/stats", response_model=TradingStatsResponse)
async def get_trading_stats(
    current_user: CurrentUser,
    db: DbSession,
    alert_id: Optional[int] = Query(default=None),
):
    """获取新闻交易绩效统计"""
    return await get_news_trading_stats(
        db,
        user_id=current_user.id,
        alert_id=alert_id,
    )
