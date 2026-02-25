"""
News Service
================
閺備即妞堟稉姘閺屻儴顕?+ 缂佺喕顓?

閼卞矁鐭?
- 閺屻儴顕楅張鈧弬鐗堟煀闂?(閺€顖涘瘮鐢胶顫?閸掑棛琚?閸忔娊鏁拠宥堢箖濠?
- 鐠侊紕鐣荤敮鍌氭簚閹懐鍗庨幐鍥ㄧ垼
- 閺備即妞堟禍銈嗘缂佲晜鏅ョ紒鐔活吀
- 閺備即妞堥惄鎴炲付鐟欏嫬鍨?CRUD
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select, desc, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle, NewsAlert, NewsThinking


logger = logging.getLogger(__name__)


# ============================================================
# 閺備即妞堥弻銉嚄
# ============================================================

async def get_latest_news(
    db: AsyncSession,
    currency: Optional[str] = None,
    news_category: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    閺屻儴顕楅張鈧弬鐗堟煀闂?
    
    Args:
        db: 閺佺増宓佹惔鎾茬窗鐠?
        currency: 鐢胶顫掓潻鍥ㄦ姢 (婵?"BTC")
        news_category: 閸掑棛琚潻鍥ㄦ姢 (婵?"macro")
        keyword: 閸忔娊鏁拠宥嗘偝缁?(閺嶅洭顣藉Ο锛勭ˇ閸栧綊鍘?
        limit: 鏉╂柨娲栭弶鈩冩殶
    
    Returns:
        閺備即妞堥崚妤勩€?(鐎涙鍚€)
    """
    query = select(NewsArticle).order_by(desc(NewsArticle.published_at))
    
    # 鐢胶顫掓潻鍥ㄦ姢 (JSON閸栧懎鎯?
    if currency:
        query = query.where(
            NewsArticle.currencies.isnot(None),
        )
    
    # 閸掑棛琚潻鍥ㄦ姢
    if news_category:
        query = query.where(NewsArticle.news_category == news_category)
    
    # 閸忔娊鏁拠宥嗘偝缁?
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
    
    # 婵″倹鐏夐張澶婄缁夊秷绻冨銈忕礉閸?Python 鐏炲倸鍟€鏉╁洦鎶?(JSON 閺屻儴顕楅崗鐓庮啇閹?
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
    鐠侊紕鐣荤敮鍌氭簚閹懐鍗庨幐鍥ㄧ垼
    
    Args:
        db: 閺佺増宓佹惔鎾茬窗鐠?
        currency: 鐢胶顫?(婵?"BTC")
        hours: 閸ョ偟婀呴弮鍫曟？缁愭褰?
    
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
    
    # 婵″倹鐏夐張澶婄缁夊秷绻冨?
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
    
    # 缂佺喕顓?
    positive_count = sum(1 for a in articles if a.sentiment == "positive")
    negative_count = sum(1 for a in articles if a.sentiment == "negative")
    neutral_count = sum(1 for a in articles if a.sentiment == "neutral")
    
    # 閸旂姵娼堥獮鍐叉綆閸?
    total_score = sum(a.sentiment_score or 0.0 for a in articles)
    avg_score = total_score / len(articles) if articles else 0.0
    
    # 閹稿鍨庣猾鑽ょ埠鐠?
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
    
    # 閺佺繝缍嬮崚銈嗘焽
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
# 閻╂垶甯剁憴鍕灟 CRUD
# ============================================================

async def get_user_alerts(
    db: AsyncSession,
    user_id: int,
    active_only: bool = False,
) -> List[Dict[str, Any]]:
    """閺屻儴顕楅悽銊﹀煕閻ㄥ嫭澧嶉張澶屾磧閹貉嗩潐閸?""
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
    閺備即妞堟禍銈嗘缂佲晜鏅ョ紒鐔活吀
    
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
# 閹繆鈧啳顔囪ぐ鏇熺叀鐠?
# ============================================================

async def get_thinkings(
    db: AsyncSession,
    user_id: int,
    news_article_id: Optional[int] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """閺屻儴顕?AI 閹繆鈧啳顔囪ぐ?""
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
# 鏉烆剚宕叉潏鍛И閸戣姤鏆?
# ============================================================

def _article_to_dict(a: NewsArticle) -> Dict[str, Any]:
    """NewsArticle ORM 閳?鐎涙鍚€"""
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
    """NewsAlert ORM 閳?鐎涙鍚€"""
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
    """NewsThinking ORM 閳?鐎涙鍚€"""
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
