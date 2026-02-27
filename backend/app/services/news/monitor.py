"""
News Monitor — Phase 2
========================
新闻关键词监控 + AI 分析 + 自动交易

流程:
1. NewsCrawler 获取新文章 → check_article() 匹配活跃规则
2. 匹配成功 → trigger_alert():
   - action=notify → 只记录 NewsThinking
   - action=trade  → AI 分析 + 趋势检查 + 自动下单
3. 全链路记录到 NewsThinking (含 AI 思考过程)
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle, NewsAlert, NewsThinking
from app.db.session import AsyncSessionLocal
from app.core.time_utils import utc_now


logger = logging.getLogger(__name__)

# 最小触发间隔 (秒)
MIN_TRIGGER_INTERVAL = 300  # 5分钟


class NewsMonitor:
    """
    新闻监控引擎

    在 NewsCrawler 获取新文章后调用 check_article() 进行匹配。
    Phase 2: 匹配后 AI 分析 + 自动交易。
    """

    async def check_article(
        self,
        db: AsyncSession,
        article: NewsArticle,
    ) -> List[NewsAlert]:
        """
        检查新文章是否匹配某个活跃的 Alert

        Args:
            db: 数据库会话
            article: 新到达的新闻

        Returns:
            匹配到的 Alert 列表
        """
        # 加载所有活跃 + 可靠的规则
        result = await db.execute(
            select(NewsAlert).where(
                NewsAlert.is_active == True,   # noqa: E712
                NewsAlert.is_reliable == True,  # noqa: E712
            )
        )
        alerts = result.scalars().all()

        matched = []
        for alert in alerts:
            if self._match(article, alert):
                matched.append(alert)
                logger.info(
                    "[NewsMonitor] 匹配: '%s' → Alert '%s'",
                    article.title[:50],
                    alert.name,
                )

        return matched

    def _match(self, article: NewsArticle, alert: NewsAlert) -> bool:
        """检查文章是否匹配规则"""
        # 1. 检查触发间隔
        if alert.last_triggered_at:
            elapsed = (
                utc_now()
                - alert.last_triggered_at
            ).total_seconds()
            if elapsed < MIN_TRIGGER_INTERVAL:
                return False

        # 2. 关键词匹配 (至少一个关键词出现在标题中)
        keywords = alert.keywords or []
        title_lower = (article.title or "").lower()
        title_zh = (article.title_zh or "").lower()

        keyword_matched = False
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in title_lower or kw_lower in title_zh:
                keyword_matched = True
                break

        if not keyword_matched:
            return False

        # 3. 分类过滤
        alert_categories = alert.news_categories or []
        if alert_categories and article.news_category:
            if article.news_category not in alert_categories:
                return False

        # 4. 币种过滤
        alert_currencies = alert.currencies or []
        if alert_currencies and article.currencies:
            overlap = set(alert_currencies) & set(article.currencies)
            if not overlap:
                return False

        # 5. 情感过滤
        if alert.sentiment_filter != "any" and article.sentiment:
            if article.sentiment != alert.sentiment_filter:
                return False

        return True

    async def trigger_alert(
        self,
        db: AsyncSession,
        article: NewsArticle,
        alert: NewsAlert,
        user_id: int,
    ) -> NewsThinking:
        """
        触发匹配的 Alert → AI 分析 + 可能执行交易

        Phase 2 完整实现:
        - action=notify → 只记录
        - action=trade  → AI 分析趋势 + 风控检查 + 自动下单
        """
        # Step 1: 获取新闻摘要
        step_news = (
            f"新闻: {article.title_zh or article.title}\n"
            f"分类: {article.news_category}, 情感: {article.sentiment} "
            f"({article.sentiment_score}), 来源: {article.source}"
        )

        # Step 2: 分析影响
        step_analyze = (
            f"规则 '{alert.name}' 匹配成功\n"
            f"情感方向: {article.sentiment}, 评分: {article.sentiment_score}\n"
            f"关联币种: {article.currencies or '未标注'}"
        )

        # 如果规则动作是 "notify" → 只记录
        if alert.action != "trade":
            thinking = NewsThinking(
                user_id=user_id,
                news_article_id=article.id,
                news_alert_id=alert.id,
                step_get_news=step_news,
                step_analyze=step_analyze,
                step_evaluate="规则动作为 notify，仅记录通知",
                step_decide="不执行交易，已通知",
                decision="watch",
            )
            db.add(thinking)
            alert.triggered_count += 1
            alert.last_triggered_at = utc_now()
            await db.flush()
            return thinking

        # ============ action=trade → AI 分析 + 自动交易 ============

        symbol = (alert.trade_symbol or "BTCUSDT").upper()
        side_config = alert.trade_side or "auto"
        leverage = alert.trade_leverage or 5
        position_pct = alert.trade_position_pct or 5.0  # 默认 5%
        sl_pct = alert.trade_stop_loss_pct or 2.0
        tp_pct = alert.trade_take_profit_pct or 3.0

        # ============ 自动判断交易方向 ============
        if side_config == "auto":
            # 根据新闻情感决定方向
            sentiment = article.sentiment or "neutral"
            score = article.sentiment_score or 0
            if sentiment == "positive" or score > 0.2:
                side = "buy"
            elif sentiment == "negative" or score < -0.2:
                side = "sell"
            else:
                # 情感中性 → 观望
                thinking = NewsThinking(
                    user_id=user_id,
                    news_article_id=article.id,
                    news_alert_id=alert.id,
                    step_get_news=step_news,
                    step_analyze=step_analyze,
                    step_evaluate="交易方向=自动, 但新闻情感为中性，无法判断方向",
                    step_decide="决策: 观望 (情感中性，自动判断无法确定方向)",
                    decision="skip",
                )
                db.add(thinking)
                alert.triggered_count += 1
                alert.last_triggered_at = utc_now()
                await db.flush()
                return thinking
            step_analyze += f"\n🤖 自动方向判断: 情感={sentiment}(score={score}) → {side}"
        else:
            side = side_config

        # Step 3: 评估 — 检查趋势分析是否支持这个方向
        step_evaluate = ""
        trend_ok = True
        trend_direction = None
        try:
            from app.models.trend_scheme import TrendScheme
            trend_result = await db.execute(
                select(TrendScheme).where(
                    TrendScheme.user_id == user_id,
                    TrendScheme.is_active == True,
                ).limit(1)
            )
            scheme = trend_result.scalar_one_or_none()
            if scheme and scheme.last_result:
                r = scheme.last_result
                trend_direction = r.get("direction", "unknown")
                regime = r.get("regime", "unknown")
                step_evaluate += (
                    f"趋势分析 ({scheme.name}): {trend_direction}, "
                    f"体制: {regime}, 置信度: {r.get('confidence', 0)}%\n"
                )

                # auto 模式: 如果趋势与情感冲突，优先用趋势方向
                if side_config == "auto" and trend_direction in ("uptrend", "downtrend"):
                    trend_side = "buy" if trend_direction == "uptrend" else "sell"
                    if trend_side != side:
                        step_evaluate += (
                            f"⚠️ 情感判断({side}) 与 趋势方向({trend_side}) 冲突 → "
                            f"采用趋势方向 {trend_side}\n"
                        )
                        side = trend_side
                    else:
                        step_evaluate += f"✅ 情感判断({side}) 与趋势方向一致\n"
                elif side_config != "auto":
                    # 固定方向模式: 检查趋势冲突
                    if side == "buy" and trend_direction == "downtrend":
                        step_evaluate += "⚠️ 趋势方向(下跌)与做多方向冲突\n"
                        trend_ok = False
                    elif side == "sell" and trend_direction == "uptrend":
                        step_evaluate += "⚠️ 趋势方向(上涨)与做空方向冲突\n"
                        trend_ok = False
                    else:
                        step_evaluate += "✅ 趋势方向与交易方向一致\n"
            else:
                step_evaluate += "未找到趋势分析结果，跳过趋势检查\n"
        except Exception as e:
            step_evaluate += f"趋势检查异常: {e}\n"

        # Step 4: 决策
        # 情感评分阈值: 只有情感明确时才交易
        sentiment_score = abs(article.sentiment_score or 0)
        if sentiment_score < 0.3:
            thinking = NewsThinking(
                user_id=user_id,
                news_article_id=article.id,
                news_alert_id=alert.id,
                step_get_news=step_news,
                step_analyze=step_analyze,
                step_evaluate=step_evaluate + "情感评分不明确 (< 0.3)，观望",
                step_decide=f"决策: 观望 (情感评分 {sentiment_score} 不够明确)",
                decision="skip",
            )
            db.add(thinking)
            alert.triggered_count += 1
            alert.last_triggered_at = utc_now()
            await db.flush()
            return thinking

        if not trend_ok:
            thinking = NewsThinking(
                user_id=user_id,
                news_article_id=article.id,
                news_alert_id=alert.id,
                step_get_news=step_news,
                step_analyze=step_analyze,
                step_evaluate=step_evaluate,
                step_decide="决策: 跳过 (趋势方向冲突，不逆势交易)",
                decision="skip",
            )
            db.add(thinking)
            alert.triggered_count += 1
            alert.last_triggered_at = utc_now()
            await db.flush()
            return thinking

        # ============ 发出标准 TradingSignal (不直接下单) ============
        step_decide = ""
        trade_action = None
        position_id = None

        try:
            from app.core.signal import TradingSignal
            from app.core.event_bus import event_bus, Event, EventType

            signal = TradingSignal(
                symbol=symbol,
                direction="long" if side == "buy" else "short",
                source="news_monitor",
                confidence=min(abs(article.sentiment_score or 0.5), 1.0),
                reason=f"[{alert.name}] {article.title_zh or article.title[:80]}",
                urgency="high",
                suggested_leverage=leverage,
                suggested_sl_pct=sl_pct,
                suggested_tp_pct=tp_pct,
                metadata={
                    "alert_id": alert.id,
                    "article_id": article.id,
                    "sentiment": article.sentiment,
                    "sentiment_score": article.sentiment_score,
                    "trend_direction": trend_direction,
                    "position_pct": position_pct,
                },
            )

            trade_action = signal.to_dict()

            # 通过 EventBus 广播信号 (由 ExternalSignalAlpha 消费 → Pipeline 执行)
            await event_bus.emit(Event(
                type=EventType.EXTERNAL_SIGNAL,
                data=signal.to_dict(),
                source="news_monitor",
                user_id=user_id,
            ))

            decision = "signal_emitted"
            step_decide = (
                f"决策: 发出交易信号 (由 Pipeline 统一执行)\n"
                f"  方向: {signal.direction}, 交易对: {symbol}\n"
                f"  信心度: {signal.confidence:.0%}\n"
                f"  建议杠杆: {leverage}x, 止损: {sl_pct}%, 止盈: {tp_pct}%\n"
                f"  触发新闻: {article.title_zh or article.title[:80]}\n"
                f"  ✅ TradingSignal 已广播至 EventBus"
            )
            logger.info(
                "[NewsMonitor] Signal emitted: %s %s %s conf=%.0f%%",
                alert.name, signal.direction, symbol, signal.confidence * 100,
            )

        except Exception as e:
            step_decide = f"决策: 信号发射异常 — {str(e)}"
            decision = "skip"
            logger.error("[NewsMonitor] trigger_alert signal error: %s", e)

        # 写入 NewsThinking
        thinking = NewsThinking(
            user_id=user_id,
            news_article_id=article.id,
            news_alert_id=alert.id,
            step_get_news=step_news,
            step_analyze=step_analyze,
            step_evaluate=step_evaluate,
            step_decide=step_decide,
            decision=decision,
            trade_action=trade_action,
            position_id=position_id,
        )
        db.add(thinking)

        # 更新 Alert 统计
        alert.triggered_count += 1
        alert.last_triggered_at = utc_now()

        await db.flush()

        logger.info(
            "[NewsMonitor] 触发 Alert '%s' → decision=%s, NewsThinking #%d",
            alert.name,
            decision,
            thinking.id,
        )

        return thinking
