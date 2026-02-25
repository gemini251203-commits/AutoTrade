"""
News Service
================
新闻业务查询 + 统计

职责:
- 查询最新新�?(支持币种/分类/关键词过�?
- 计算市场情绪指标
- 新闻交易绩效统计
- 新闻监控规则 CRUD
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select, desc, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle, NewsAlert, NewsThinking


logger = logging.getLogger(__name__)


# ============================================================
# 新闻查询
# ============================================================

async def get_latest_news(
    db: AsyncSession,
    currency: Optional[str] = None,
    news_category: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    查询最新新�?
    
    Args:
        db: 数据库会�?
        currency: 币种过滤 (�?"BTC")
        news_category: 分类过滤 (�?"macro")
        keyword: 关键词搜�?(标题模糊匹配)
        limit: 返回条数
    
    Returns:
        新闻列表 (字典)
    """
    query = select(NewsArticle).order_by(desc(NewsArticle.published_at))
    
    # 币种过滤 (JSON包含)
    if currency:
        query = query.where(
            NewsArticle.currencies.isnot(None),
        )
    
    # 分类过滤
    if news_category:
        query = query.where(NewsArticle.news_category == news_category)
    
    # 关键词搜�?
    if keyword:
        query = query.where(
            or_(
                NewsArticle.title.ilike(f"%{keyword}%"),
                NewsArticle.title_zh.ilike(f"%{keyword}%"),
            )
        )
    
    query = query.limit(limit)
    result = await db.execute(query)
    articles = result.scalars().all()
    
    # 如果有币种过滤，�?Python 层再过滤 (JSON 查询兼容�?
    if currency:
        currency_upper = currency.upper()
        articles = [
            a for a in articles
            if a.currencies and currency_upper in a.currencies
        ]
    
    return [_article_to_dict(a) for a in articles]


async def get_market_sentiment(
    db: AsyncSession,
    currency: Optional[str] = None,
    hours: int = 24,
) -> Dict[str, Any]:
    """
    计算市场情绪指标
    
    Args:
        db: 数据库会�?
        currency: 币种 (�?"BTC")
        hours: 回看时间窗口
    
    Returns:
        {
            "overall": "positive",
            "score": 0.35,
            "total_articles": 42,
            "positive_count": 25,
            "negative_count": 8,
            "neutral_count": 9,
            "by_category": {...},
        }
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    
    query = select(NewsArticle).where(
        NewsArticle.published_at >= since,
    )
    
    result = await db.execute(query)
    articles = result.scalars().all()
    
    # 如果有币种过�?
    if currency:
        currency_upper = currency.upper()
        articles = [
            a for a in articles
            if a.currencies and currency_upper in a.currencies
        ]
    
    if not articles:
        return {
            "overall": "neutral",
            "score": 0.0,
            "total_articles": 0,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "by_category": {},
            "hours": hours,
            "currency": currency,
        }
    
    # 统计
    positive_count = sum(1 for a in articles if a.sentiment == "positive")
    negative_count = sum(1 for a in articles if a.sentiment == "negative")
    neutral_count = sum(1 for a in articles if a.sentiment == "neutral")
    
    # 加权平均�?
    total_score = sum(a.sentiment_score or 0.0 for a in articles)
    avg_score = total_score / len(articles) if articles else 0.0
    
    # 按分类统�?
    by_category: Dict[str, Dict] = {}
    for a in articles:
        cat = a.news_category or "other"
        if cat not in by_category:
            by_category[cat] = {"count": 0, "avg_score": 0.0, "total_score": 0.0}
        by_category[cat]["count"] += 1
        by_category[cat]["total_score"] += (a.sentiment_score or 0.0)
    
    for cat_data in by_category.values():
        if cat_data["count"] > 0:
            cat_data["avg_score"] = round(
                cat_data["total_score"] / cat_data["count"], 3
            )
        del cat_data["total_score"]
    
    # 整体判断
    if avg_score > 0.15:
        overall = "positive"
    elif avg_score < -0.15:
        overall = "negative"
    else:
        overall = "neutral"
    
    return {
        "overall": overall,
        "score": round(avg_score, 3),
        "total_articles": len(articles),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
        "by_category": by_category,
        "hours": hours,
        "currency": currency,
    }


# ============================================================
# 监控规则 CRUD
# ============================================================

async def get_user_alerts(
    db: AsyncSession,
    user_id: int,
    active_only: bool = False,
) -> List[Dict[str, Any]]:
    """查询用户的所有监控规�?""
    query = (
        select(NewsAlert)
        .where(NewsAlert.user_id == user_id)
        .order_by(desc(NewsAlert.created_at))
    )
    if active_only:
        query = query.where(NewsAlert.is_active == True)  # noqa: E712
    
    result = await db.execute(query)
    alerts = result.scalars().all()
    return [_alert_to_dict(a) for a in alerts]


async def get_news_trading_stats(
    db: AsyncSession,
    user_id: int,
    alert_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    新闻交易绩效统计
    
    Returns:
        {
            "total_trades": 15,
            "win_count": 9,
            "loss_count": 6,
            "win_rate": 60.0,
            "total_pnl": 156.78,
            "by_category": {...},
        }
    """
    query = select(NewsThinking).where(
        NewsThinking.user_id == user_id,
        NewsThinking.decision == "trade",
        NewsThinking.trade_result.isnot(None),
    )
    if alert_id:
        query = query.where(NewsThinking.news_alert_id == alert_id)
    
    result = await db.execute(query)
    thinkings = result.scalars().all()
    
    if not thinkings:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "by_category": {},
        }
    
    win_count = sum(1 for t in thinkings if t.trade_result == "win")
    loss_count = sum(1 for t in thinkings if t.trade_result == "loss")
    total_pnl = sum(t.trade_pnl or 0.0 for t in thinkings)
    total_trades = len(thinkings)
    
    return {
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_count / total_trades * 100, 1) if total_trades > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
    }


# ============================================================
# 思考记录查�?
# ============================================================

async def get_thinkings(
    db: AsyncSession,
    user_id: int,
    news_article_id: Optional[int] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """查询 AI 思考记�?""
    query = (
        select(NewsThinking)
        .where(NewsThinking.user_id == user_id)
        .order_by(desc(NewsThinking.created_at))
    )
    if news_article_id:
        query = query.where(NewsThinking.news_article_id == news_article_id)
    
    query = query.limit(limit)
    result = await db.execute(query)
    thinkings = result.scalars().all()
    return [_thinking_to_dict(t) for t in thinkings]


# ============================================================
# 转换辅助函数
# ============================================================

def _article_to_dict(a: NewsArticle) -> Dict[str, Any]:
    """NewsArticle ORM �?字典"""
    return {
        "id": a.id,
        "source": a.source,
        "title": a.title,
        "title_zh": a.title_zh,
        "url": a.url,
        "currencies": a.currencies,
        "news_category": a.news_category,
        "sentiment": a.sentiment,
        "sentiment_score": a.sentiment_score,
        "importance": a.importance,
        "votes_positive": a.votes_positive,
        "votes_negative": a.votes_negative,
        "published_at": a.published_at.isoformat() + "Z" if a.published_at else "",
        "created_at": a.created_at.isoformat() + "Z" if a.created_at else "",
    }


def _alert_to_dict(a: NewsAlert) -> Dict[str, Any]:
    """NewsAlert ORM �?字典"""
    win_rate = 0.0
    total = a.win_count + a.loss_count
    if total > 0:
        win_rate = round(a.win_count / total * 100, 1)
    
    return {
        "id": a.id,
        "user_id": a.user_id,
        "name": a.name,
        "keywords": a.keywords,
        "news_categories": a.news_categories,
        "currencies": a.currencies,
        "sentiment_filter": a.sentiment_filter,
        "action": a.action,
        "trade_side": a.trade_side,
        "trade_symbol": a.trade_symbol,
        "trade_position_pct": a.trade_position_pct,
        "trade_leverage": a.trade_leverage,
        "trade_stop_loss_pct": a.trade_stop_loss_pct,
        "trade_take_profit_pct": a.trade_take_profit_pct,
        "is_active": a.is_active,
        "is_reliable": a.is_reliable,
        "reliability_note": a.reliability_note,
        "triggered_count": a.triggered_count,
        "win_count": a.win_count,
        "loss_count": a.loss_count,
        "total_pnl": a.total_pnl,
        "win_rate": win_rate,
        "last_triggered_at": (
            a.last_triggered_at.isoformat() + "Z" if a.last_triggered_at else None
        ),
        "created_at": a.created_at.isoformat() + "Z" if a.created_at else "",
    }


def _thinking_to_dict(t: NewsThinking) -> Dict[str, Any]:
    """NewsThinking ORM �?字典"""
    return {
        "id": t.id,
        "user_id": t.user_id,
        "news_article_id": t.news_article_id,
        "news_alert_id": t.news_alert_id,
        "step_get_news": t.step_get_news,
        "step_analyze": t.step_analyze,
        "step_evaluate": t.step_evaluate,
        "step_decide": t.step_decide,
        "decision": t.decision,
        "trade_action": t.trade_action,
        "position_id": t.position_id,
        "trade_result": t.trade_result,
        "trade_pnl": t.trade_pnl,
        "ai_reflection": t.ai_reflection,
        "created_at": t.created_at.isoformat() + "Z" if t.created_at else "",
    }
