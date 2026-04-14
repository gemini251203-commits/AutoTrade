"""
新闻+预警+纪要搜索+唤醒条件工具
=================================
get_news, get_market_sentiment, list_alerts, create_alert, update_alert,
analyze_news_impact, auto_generate_alerts, search_historical_minutes, set_wake_conditions
"""

import json
from collections import defaultdict
from datetime import date, timedelta, timezone
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.time_utils import utc_now
from ._registry import register_tool


# ==================== 新闻工具 ====================

@register_tool
async def get_news(
    db: AsyncSession,
    user_id: int,
    currency: str = "BTC",
    limit: int = 10,
) -> str:
    """
    查询最新加密货币新闻

    参数:
        currency: 币种过滤, 如 BTC / ETH / SOL (空=全部)
        limit: 返回条数 (默认10, 最大50)

    返回:
        新闻列表 (标题、中文标题、情绪、重要性、来源、时间)
    """
    from app.services.news.service import get_latest_news

    try:
        articles = await get_latest_news(
            db,
            currency=currency if currency else None,
            limit=min(limit, 50),
        )

        if not articles:
            return json.dumps({"message": f"暂无 {currency} 相关新闻"}, ensure_ascii=False, default=str)

        result = []
        for a in articles[:limit]:
            result.append({
                "title": a.get("title", ""),
                "title_zh": a.get("title_zh", ""),
                "sentiment": a.get("sentiment", "unknown"),
                "sentiment_score": a.get("sentiment_score"),
                "importance": a.get("importance", ""),
                "source": a.get("source", ""),
                "published_at": a.get("published_at", ""),
            })

        return json.dumps({
            "currency": currency,
            "count": len(result),
            "articles": result,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


@register_tool
async def get_market_sentiment(
    db: AsyncSession,
    user_id: int,
    currency: str = "BTC",
) -> str:
    """
    查询市场情绪 (基于新闻情感分析)

    参数:
        currency: 币种, 如 BTC / ETH (空=全部)

    返回:
        整体情绪(看多/看空/中性)、情绪分数、正面/负面/中性新闻数量
    """
    from app.services.news.service import get_market_sentiment as _get_sentiment

    try:
        sentiment = await _get_sentiment(
            db,
            currency=currency if currency else None,
            hours=24,
        )

        overall = sentiment.get("overall", "neutral")
        overall_zh = {"positive": "看多", "negative": "看空", "neutral": "中性"}.get(overall, overall)

        return json.dumps({
            "currency": currency,
            "overall": overall_zh,
            "score": sentiment.get("score", 0),
            "total_articles": sentiment.get("total_articles", 0),
            "positive_count": sentiment.get("positive_count", 0),
            "negative_count": sentiment.get("negative_count", 0),
            "neutral_count": sentiment.get("neutral_count", 0),
            "by_category": sentiment.get("by_category", {}),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


# ==================== 新闻监控规则工具 ====================

@register_tool
async def list_alerts(
    db: AsyncSession,
    user_id: int,
) -> str:
    """
    查看所有新闻监控规则

    返回:
        监控规则列表 (名称、关键词、触发次数、胜率、总盈亏)
    """
    from app.services.news.service import get_user_alerts, _alert_to_dict

    try:
        alerts = await get_user_alerts(db, user_id=user_id)

        if not alerts:
            return json.dumps({"message": "暂无监控规则，可使用 create_alert 创建"}, ensure_ascii=False, default=str)

        result = []
        for a in alerts:
            result.append({
                "id": a["id"],
                "name": a["name"],
                "keywords": a["keywords"],
                "action": a["action"],
                "is_active": a["is_active"],
                "trade_symbol": a.get("trade_symbol"),
                "trade_side": a.get("trade_side"),
                "triggered_count": a["triggered_count"],
                "win_count": a["win_count"],
                "loss_count": a["loss_count"],
                "win_rate": a["win_rate"],
                "total_pnl": a["total_pnl"],
            })

        return json.dumps({
            "count": len(result),
            "alerts": result,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


@register_tool
async def create_alert(
    db: AsyncSession,
    user_id: int,
    name: str = "",
    keywords: str = "",
    action: str = "notify",
    trade_symbol: str = "BTCUSDT",
    trade_side: str = "auto",
    trade_position_pct: float = 5.0,
    trade_leverage: int = 5,
    trade_stop_loss_pct: float = 2.0,
    trade_take_profit_pct: float = 3.0,
    news_categories: str = "",
    currencies: str = "",
    sentiment_filter: str = "any",
) -> str:
    """
    创建新闻监控规则

    参数:
        name: 规则名称, 如 "ETF利好做多"
        keywords: 关键词列表, 逗号分隔, 如 "ETF,BlackRock,降息"
        action: 动作类型, notify=仅通知, trade=自动交易
        trade_symbol: 交易对 (action=trade时生效)
        trade_side: 交易方向, buy/sell/auto (auto=根据新闻情感自动判断)
        trade_position_pct: 仓位比例% (1-15)
        trade_leverage: 杠杆倍数 (1-20)
        trade_stop_loss_pct: 止损百分比
        trade_take_profit_pct: 止盈百分比
        news_categories: 可选, 分类过滤, 逗号分隔 (macro/etf/regulation/exchange/whale/project)
        currencies: 可选, 币种过滤, 逗号分隔 (BTC/ETH/SOL)
        sentiment_filter: 情感过滤, any/positive/negative
    """
    from app.models.news import NewsAlert
    from app.services.news.service import get_user_alerts, _alert_to_dict

    try:
        if not name:
            return json.dumps({"error": "请提供规则名称 (name)"}, ensure_ascii=False, default=str)
        if not keywords:
            return json.dumps({"error": "请提供关键词 (keywords), 逗号分隔"}, ensure_ascii=False, default=str)

        # 检查规则数量限制
        existing = await get_user_alerts(db, user_id=user_id)
        if len(existing) >= 20:
            return json.dumps({"error": "监控规则已达上限 (20条)"}, ensure_ascii=False, default=str)

        # 解析逗号分隔的列表
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        cat_list = [c.strip() for c in news_categories.split(",") if c.strip()] if news_categories else None
        cur_list = [c.strip().upper() for c in currencies.split(",") if c.strip()] if currencies else None

        # 验证 trade 模式参数
        if action == "trade" and not trade_symbol:
            return json.dumps({"error": "交易模式需要指定 trade_symbol"}, ensure_ascii=False, default=str)

        alert = NewsAlert(
            user_id=user_id,
            name=name,
            keywords=kw_list,
            news_categories=cat_list,
            currencies=cur_list,
            sentiment_filter=sentiment_filter,
            action=action,
            trade_side=trade_side if action == "trade" else None,
            trade_symbol=trade_symbol if action == "trade" else None,
            trade_position_pct=trade_position_pct if action == "trade" else None,
            trade_leverage=trade_leverage if action == "trade" else None,
            trade_stop_loss_pct=trade_stop_loss_pct if action == "trade" else None,
            trade_take_profit_pct=trade_take_profit_pct if action == "trade" else None,
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)

        result = _alert_to_dict(alert)
        return json.dumps({
            "message": f"监控规则 '{name}' 创建成功",
            "alert": result,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


@register_tool
async def update_alert(
    db: AsyncSession,
    user_id: int,
    alert_id: int = 0,
    action: str = "",
    name: str = "",
    keywords: str = "",
    is_active: str = "",
    trade_side: str = "",
    trade_symbol: str = "",
    trade_position_pct: float = 0,
    trade_leverage: int = 0,
    trade_stop_loss_pct: float = 0,
    trade_take_profit_pct: float = 0,
) -> str:
    """
    修改/启停/删除新闻监控规则

    参数:
        alert_id: 规则 ID (必填)
        action: 操作类型 - update/activate/deactivate/delete
    """
    from sqlalchemy import select as sa_select
    from app.models.news import NewsAlert
    from app.services.news.service import _alert_to_dict

    try:
        if alert_id <= 0:
            return json.dumps({"error": "请提供规则 ID (alert_id)"}, ensure_ascii=False, default=str)

        result = await db.execute(
            sa_select(NewsAlert).where(
                NewsAlert.id == alert_id,
                NewsAlert.user_id == user_id,
            )
        )
        alert = result.scalar_one_or_none()
        if not alert:
            return json.dumps({"error": f"规则 #{alert_id} 不存在"}, ensure_ascii=False, default=str)

        # 删除操作
        if action == "delete":
            alert_name = alert.name
            await db.delete(alert)
            await db.commit()
            return json.dumps({"message": f"规则 '{alert_name}' 已删除"}, ensure_ascii=False, default=str)

        # 快捷启停
        if action == "activate":
            alert.is_active = True
            await db.commit()
            return json.dumps({"message": f"规则 '{alert.name}' 已启用"}, ensure_ascii=False, default=str)
        if action == "deactivate":
            alert.is_active = False
            await db.commit()
            return json.dumps({"message": f"规则 '{alert.name}' 已暂停"}, ensure_ascii=False, default=str)

        # 逐字段更新
        if name:
            alert.name = name
        if keywords:
            alert.keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        if is_active:
            alert.is_active = is_active.lower() == "true"
        if trade_side:
            alert.trade_side = trade_side
        if trade_symbol:
            alert.trade_symbol = trade_symbol
        if trade_position_pct > 0:
            alert.trade_position_pct = trade_position_pct
        if trade_leverage > 0:
            alert.trade_leverage = trade_leverage
        if trade_stop_loss_pct > 0:
            alert.trade_stop_loss_pct = trade_stop_loss_pct
        if trade_take_profit_pct > 0:
            alert.trade_take_profit_pct = trade_take_profit_pct

        await db.commit()
        await db.refresh(alert)

        return json.dumps({
            "message": f"规则 '{alert.name}' 已更新",
            "alert": _alert_to_dict(alert),
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


# ==================== 新闻-市场关联分析 ====================

@register_tool
async def analyze_news_impact(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    days: int = 30,
    window_hours: str = "1,4,24",
) -> str:
    """
    分析新闻对市场的影响 — 发现新闻-价格关联规律

    参数:
        symbol: 交易对 (默认 BTCUSDT)
        days: 回看天数 (默认30, 最大90)
        window_hours: 观察窗口, 逗号分隔 (默认 "1,4,24")
    """
    from sqlalchemy import select as sa_select, and_
    from app.models.news import NewsArticle
    from app.models.market import Kline

    try:
        days = min(days, 90)
        windows = [int(h.strip()) for h in window_hours.split(",") if h.strip()]
        if not windows:
            windows = [1, 4, 24]

        cutoff = utc_now() - timedelta(days=days)

        # 1. 查询新闻
        news_result = await db.execute(
            sa_select(NewsArticle).where(
                NewsArticle.published_at >= cutoff,
            ).order_by(NewsArticle.published_at.desc()).limit(500)
        )
        articles = news_result.scalars().all()

        if not articles:
            return json.dumps({
                "message": f"过去 {days} 天没有新闻数据，无法分析",
            }, ensure_ascii=False, default=str)

        # 2. 对每条新闻，获取发布时 + 各窗口后的价格
        base_symbol = symbol.upper()
        impact_records = []

        for article in articles:
            pub_ts = int(article.published_at.timestamp() * 1000)

            base_kline = await db.execute(
                sa_select(Kline).where(
                    and_(
                        Kline.symbol == base_symbol,
                        Kline.interval == "1h",
                        Kline.open_time <= pub_ts,
                    )
                ).order_by(Kline.open_time.desc()).limit(1)
            )
            base_k = base_kline.scalar_one_or_none()
            if not base_k:
                continue

            base_price = float(base_k.close)
            if base_price <= 0:
                continue

            changes = {}
            for w in windows:
                target_ts = pub_ts + w * 3600 * 1000
                future_kline = await db.execute(
                    sa_select(Kline).where(
                        and_(
                            Kline.symbol == base_symbol,
                            Kline.interval == "1h",
                            Kline.open_time <= target_ts,
                        )
                    ).order_by(Kline.open_time.desc()).limit(1)
                )
                future_k = future_kline.scalar_one_or_none()
                if future_k:
                    future_price = float(future_k.close)
                    pct_change = ((future_price - base_price) / base_price) * 100
                    changes[f"{w}h"] = round(pct_change, 3)

            if not changes:
                continue

            impact_records.append({
                "title": article.title[:60],
                "category": article.news_category or "other",
                "sentiment": article.sentiment or "neutral",
                "importance": article.importance or "low",
                "published_at": str(article.published_at),
                "base_price": base_price,
                "changes": changes,
            })

        if not impact_records:
            return json.dumps({
                "message": f"有 {len(articles)} 条新闻但无法匹配到 {base_symbol} K线数据",
            }, ensure_ascii=False, default=str)

        # 3. 按 (category, sentiment) 分组统计
        groups = defaultdict(list)
        for rec in impact_records:
            key = f"{rec['category']}|{rec['sentiment']}"
            groups[key].append(rec)

        # 4. 计算统计指标
        group_stats = []
        for key, records in groups.items():
            category, sentiment = key.split("|")
            sample_count = len(records)
            if sample_count < 2:
                continue

            stats_entry = {
                "category": category,
                "sentiment": sentiment,
                "sample_count": sample_count,
            }

            for w in windows:
                w_key = f"{w}h"
                changes_in_window = [r["changes"].get(w_key) for r in records if w_key in r["changes"]]
                if not changes_in_window:
                    continue

                avg_change = sum(changes_in_window) / len(changes_in_window)
                positive_count = sum(1 for c in changes_in_window if c > 0)
                win_rate = positive_count / len(changes_in_window) * 100
                max_up = max(changes_in_window)
                max_down = min(changes_in_window)

                stats_entry[f"{w_key}_avg_change"] = round(avg_change, 3)
                stats_entry[f"{w_key}_win_rate"] = round(win_rate, 1)
                stats_entry[f"{w_key}_max_up"] = round(max_up, 2)
                stats_entry[f"{w_key}_max_down"] = round(max_down, 2)
                stats_entry[f"{w_key}_samples"] = len(changes_in_window)

            group_stats.append(stats_entry)

        sort_key = "4h_avg_change" if "4h" in windows else f"{windows[0]}h_avg_change"
        group_stats.sort(key=lambda x: abs(x.get(sort_key, 0)), reverse=True)

        # 5. 发现规律 (显著模式)
        patterns = []
        for s in group_stats:
            for w in windows:
                w_key = f"{w}h"
                avg = s.get(f"{w_key}_avg_change", 0)
                wr = s.get(f"{w_key}_win_rate", 50)
                samples = s.get(f"{w_key}_samples", 0)
                if samples < 3:
                    continue

                if avg > 0.5 and wr >= 60:
                    patterns.append({
                        "rule": f"{s['category']}类 + {s['sentiment']}情感 → {w}h后平均涨{avg:.2f}%",
                        "direction": "做多",
                        "avg_change": avg,
                        "win_rate": wr,
                        "confidence": "高" if (samples >= 5 and wr >= 70) else "中",
                        "category": s["category"],
                        "sentiment": s["sentiment"],
                        "window": w,
                        "samples": samples,
                    })
                elif avg < -0.5 and wr <= 40:
                    real_wr = 100 - wr
                    patterns.append({
                        "rule": f"{s['category']}类 + {s['sentiment']}情感 → {w}h后平均跌{abs(avg):.2f}%",
                        "direction": "做空",
                        "avg_change": avg,
                        "win_rate": real_wr,
                        "confidence": "高" if (samples >= 5 and real_wr >= 70) else "中",
                        "category": s["category"],
                        "sentiment": s["sentiment"],
                        "window": w,
                        "samples": samples,
                    })

        patterns.sort(key=lambda x: abs(x["avg_change"]), reverse=True)

        return json.dumps({
            "symbol": base_symbol,
            "analysis_period": f"过去{days}天",
            "total_news": len(articles),
            "matched_news": len(impact_records),
            "windows": [f"{w}h" for w in windows],
            "group_stats": group_stats[:15],
            "discovered_patterns": patterns[:10],
            "hint": "使用 auto_generate_alerts 可将发现的规律自动创建为监控规则",
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


@register_tool
async def auto_generate_alerts(
    db: AsyncSession,
    user_id: int,
    symbol: str = "BTCUSDT",
    days: int = 30,
    min_win_rate: float = 60.0,
    min_samples: int = 3,
    action: str = "notify",
    trade_position_pct: float = 5.0,
    trade_leverage: int = 3,
    trade_stop_loss_pct: float = 2.0,
    trade_take_profit_pct: float = 4.0,
) -> str:
    """
    根据历史新闻-市场关联分析, 自动生成监控规则

    参数:
        symbol: 交易对 (默认 BTCUSDT)
        days: 分析回看天数 (默认30)
        min_win_rate: 最低胜率阈值% (默认60)
        min_samples: 最少样本数 (默认3)
        action: 规则动作, notify=仅通知, trade=自动交易
    """
    from app.models.news import NewsAlert
    from app.services.news.service import get_user_alerts

    try:
        # 1. 先运行分析
        analysis_result = await analyze_news_impact(
            db=db,
            user_id=user_id,
            symbol=symbol,
            days=days,
            window_hours="1,4,24",
        )
        analysis = json.loads(analysis_result)

        if "error" in analysis:
            return json.dumps({"error": analysis["error"]}, ensure_ascii=False, default=str)

        patterns = analysis.get("discovered_patterns", [])
        if not patterns:
            return json.dumps({
                "message": f"过去{days}天未发现显著的新闻-市场关联规律 (需要更多数据)",
                "total_news_analyzed": analysis.get("total_news", 0),
            }, ensure_ascii=False, default=str)

        # 2. 检查已有规则数量
        existing = await get_user_alerts(db, user_id=user_id)
        remaining_slots = 20 - len(existing)
        if remaining_slots <= 0:
            return json.dumps({"error": "监控规则已达上限(20条), 请先删除旧规则"}, ensure_ascii=False, default=str)

        # 3. 按规则生成 Alert
        category_keywords = {
            "macro": ["fed", "rate cut", "rate hike", "inflation", "CPI", "GDP", "FOMC", "联储", "降息", "加息"],
            "etf": ["ETF", "BlackRock", "Grayscale", "Fidelity", "inflow", "outflow", "spot ETF"],
            "regulation": ["SEC", "regulation", "lawsuit", "compliance", "ban", "license", "监管"],
            "exchange": ["Binance", "Coinbase", "listing", "delist", "exchange", "上币"],
            "whale": ["whale", "transfer", "wallet", "dormant", "accumulation", "巨鲸"],
            "project": ["upgrade", "fork", "mainnet", "partnership", "hack", "exploit", "airdrop"],
        }

        created_alerts = []
        for pattern in patterns:
            if len(created_alerts) >= remaining_slots:
                break

            win_rate = pattern.get("win_rate", 0)
            samples = pattern.get("samples", 0)

            if win_rate < min_win_rate or samples < min_samples:
                continue

            category = pattern["category"]
            sentiment = pattern["sentiment"]
            direction = pattern["direction"]
            avg_change = pattern["avg_change"]
            window = pattern.get("window", 4)

            cat_zh = {
                "macro": "宏观", "etf": "ETF", "regulation": "监管",
                "exchange": "交易所", "whale": "巨鲸", "project": "项目",
            }.get(category, category)
            sent_zh = {"positive": "利好", "negative": "利空", "neutral": "中性"}.get(sentiment, sentiment)

            name = f"[AI发现] {cat_zh}{sent_zh}→{direction} ({win_rate:.0f}%胜率)"

            if any(e.get("name") == name for e in existing):
                continue

            keywords = category_keywords.get(category, [category])
            trade_side = "buy" if direction == "做多" else "sell"
            sentiment_filter = sentiment if sentiment != "neutral" else "any"

            alert = NewsAlert(
                user_id=user_id,
                name=name,
                keywords=keywords,
                news_categories=[category] if category != "other" else None,
                currencies=None,
                sentiment_filter=sentiment_filter,
                action=action,
                trade_side=trade_side if action == "trade" else None,
                trade_symbol=symbol if action == "trade" else None,
                trade_position_pct=trade_position_pct if action == "trade" else None,
                trade_leverage=trade_leverage if action == "trade" else None,
                trade_stop_loss_pct=trade_stop_loss_pct if action == "trade" else None,
                trade_take_profit_pct=trade_take_profit_pct if action == "trade" else None,
            )
            db.add(alert)
            await db.flush()

            created_alerts.append({
                "id": alert.id,
                "name": name,
                "category": category,
                "sentiment": sentiment,
                "direction": direction,
                "avg_change": f"{avg_change:+.2f}%",
                "win_rate": f"{win_rate:.0f}%",
                "samples": samples,
                "keywords": keywords[:5],
                "action": action,
            })

        if created_alerts:
            await db.commit()

        return json.dumps({
            "message": f"基于过去{days}天分析, 自动创建了 {len(created_alerts)} 条监控规则",
            "analysis_summary": {
                "total_news": analysis.get("total_news", 0),
                "matched_news": analysis.get("matched_news", 0),
                "patterns_found": len(patterns),
                "rules_created": len(created_alerts),
            },
            "created_alerts": created_alerts,
            "skipped_reason": f"跳过胜率<{min_win_rate}%或样本<{min_samples}的模式" if len(patterns) > len(created_alerts) else None,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False, default=str)


# ==================== 董事会记忆工具 ====================

@register_tool
async def search_historical_minutes(
    db: AsyncSession,
    user_id: int,
    keyword: str = "",
    days_back: int = 90,
    semantic: bool = True,
) -> str:
    """
    搜索历史董事会纪要 — 深层冷记忆检索

    参数:
        keyword: 搜索内容 (如 "暴跌后怎么办", "止损教训")
        days_back: 往回搜索天数 (默认 90 天, 最大 365)
        semantic: 是否使用语义搜索 (默认 True)
    """
    # ★ 语义搜索模式 — 优先尝试 mem0
    if semantic and keyword and keyword.strip():
        try:
            from app.services.hub.memory_service import search_memories
            memories = await search_memories(user_id, keyword.strip(), limit=5)
            if memories:
                data = []
                for mem in memories:
                    data.append({
                        "memory": mem.get("memory", ""),
                        "score": f"{mem.get('score', 0):.0%}",
                        "metadata": mem.get("metadata", {}),
                    })
                return json.dumps({
                    "results": data,
                    "total": len(data),
                    "search_mode": "semantic",
                    "query": keyword,
                }, ensure_ascii=False, default=str)
        except Exception as e:
            logger.debug(f"[AgentTools] Semantic search unavailable, falling back to keyword: {e}")

    # ★ 关键词搜索 fallback
    from app.models.board_minutes import BoardMinutes

    days_back = min(int(days_back), 365)
    cutoff = date.today() - timedelta(days=days_back)

    try:
        query = select(BoardMinutes).where(
            BoardMinutes.user_id == user_id,
            BoardMinutes.date >= cutoff,
        )

        if keyword and keyword.strip():
            kw = f"%{keyword.strip()}%"
            from sqlalchemy import or_
            query = query.where(
                or_(
                    BoardMinutes.summary.ilike(kw),
                    BoardMinutes.key_lessons.ilike(kw),
                )
            )

        query = query.order_by(BoardMinutes.date.desc()).limit(10)
        result = await db.execute(query)
        minutes = result.scalars().all()

        if not minutes:
            return json.dumps({
                "results": [],
                "message": f"过去 {days_back} 天内未找到包含「{keyword}」的纪要",
            }, ensure_ascii=False, default=str)

        data = []
        for m in minutes:
            pnl_sign = "+" if m.pnl_total >= 0 else ""
            data.append({
                "date": str(m.date),
                "importance": m.importance,
                "trade_count": m.trade_count,
                "pnl": f"{pnl_sign}{m.pnl_total:.1f} USDT",
                "summary": m.summary[:200],
                "key_lessons": m.key_lessons,
            })

        return json.dumps({
            "results": data,
            "total": len(data),
            "search_mode": "keyword",
            "search_range": f"过去 {days_back} 天",
            "keyword": keyword,
        }, ensure_ascii=False, default=str)

    except Exception as e:
        logger.warning(f"[AgentTools] search_historical_minutes error: {e}")
        return json.dumps({"error": f"搜索失败: {str(e)}"}, ensure_ascii=False, default=str)


# ==================== 唤醒条件工具 ====================

@register_tool
async def set_wake_conditions(
    db: AsyncSession,
    user_id: int,
    conditions_json: str = "[]",
    timeout_minutes: int = 30,
) -> str:
    """
    设定唤醒条件 — 告诉系统什么时候需要立即唤醒你

    条件类型:
    - price_above: 价格突破上方
    - price_below: 价格跌破下方
    - change_pct: 价格变化超过百分比

    参数:
        conditions_json: 唤醒条件数组 (JSON)
        timeout_minutes: 超时兜底 (5-60分钟)
    """
    # ★ 健壮的参数解析
    try:
        if isinstance(conditions_json, str):
            conditions = json.loads(conditions_json)
        elif isinstance(conditions_json, list):
            conditions = conditions_json
        elif isinstance(conditions_json, dict):
            conditions = [conditions_json]
        else:
            conditions = json.loads(str(conditions_json))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"[AgentTools] set_wake_conditions parse error: {e}, raw={conditions_json!r}")
        return json.dumps({"error": f"conditions_json 格式错误: {str(e)}，需要 JSON 数组"}, ensure_ascii=False)

    if not isinstance(conditions, list) or len(conditions) == 0:
        return json.dumps({"error": "请至少设定一个唤醒条件"}, ensure_ascii=False)

    # ★ 安全的 timeout_minutes 类型转换
    try:
        timeout_minutes = int(float(timeout_minutes))
    except (ValueError, TypeError):
        timeout_minutes = 30

    # 验证条件格式
    valid_types = {"price_above", "price_below", "change_pct"}
    for i, cond in enumerate(conditions):
        if not isinstance(cond, dict):
            return json.dumps({"error": f"第 {i+1} 个条件格式错误，需要 dict"}, ensure_ascii=False)
        ctype = cond.get("type", "")
        if ctype not in valid_types:
            return json.dumps({
                "error": f"第 {i+1} 个条件类型 '{ctype}' 无效，有效类型: {valid_types}"
            }, ensure_ascii=False)
        if ctype in ("price_above", "price_below") and not cond.get("symbol"):
            return json.dumps({
                "error": f"第 {i+1} 个条件 {ctype} 需要指定 symbol"
            }, ensure_ascii=False)
        try:
            val = float(cond.get("value", 0))
            if val <= 0:
                return json.dumps({"error": f"第 {i+1} 个条件 value 必须大于 0"}, ensure_ascii=False)
        except (ValueError, TypeError):
            return json.dumps({"error": f"第 {i+1} 个条件 value 格式错误"}, ensure_ascii=False)

    # 从 Redis 获取 agent_id
    agent_id = 0
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            agent_id_str = await r.get(f"hub:current_agent:{user_id}")
            if agent_id_str:
                agent_id = int(agent_id_str)
        finally:
            await r.aclose()
    except Exception as e:
        logger.warning(f"[AgentTools] set_wake_conditions Redis error: {e}")

    if not agent_id:
        logger.warning(f"[AgentTools] set_wake_conditions: no agent_id found in Redis for user {user_id}")
        return json.dumps({
            "error": "无法获取当前 Agent ID，唤醒条件设定失败。此工具仅在值班循环中可用。"
        }, ensure_ascii=False)

    # 调用 WakeMonitor 设定条件
    try:
        from app.services.hub.wake_monitor import wake_monitor
        result = await wake_monitor.set_conditions(
            user_id=user_id,
            agent_id=agent_id,
            conditions=conditions,
            timeout_minutes=timeout_minutes,
        )
        logger.info(f"[AgentTools] set_wake_conditions SUCCESS: agent={agent_id}, conditions={len(conditions)}, timeout={timeout_minutes}min")
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[AgentTools] set_wake_conditions failed: {e}")
        return json.dumps({"error": f"设定唤醒条件失败: {str(e)}"}, ensure_ascii=False)
