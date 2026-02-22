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
                datetime.utcnow()
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
            alert.last_triggered_at = datetime.utcnow()
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
                alert.last_triggered_at = datetime.utcnow()
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
            alert.last_triggered_at = datetime.utcnow()
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
            alert.last_triggered_at = datetime.utcnow()
            await db.flush()
            return thinking

        # ============ 执行交易 ============
        step_decide = ""
        trade_action = None
        position_id = None

        try:
            # 获取当前价格
            from app.services.exchange import BinanceClient
            client = BinanceClient()
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker.get("lastPrice", 0)) if ticker else 0

            if current_price <= 0:
                step_decide = "决策: 跳过 (无法获取当前价格)"
                decision = "skip"
            else:
                # 计算下单数量
                from app.models.wallet import Wallet
                wallet_result = await db.execute(
                    select(Wallet).where(Wallet.user_id == user_id)
                )
                wallet = wallet_result.scalar_one_or_none()
                if not wallet or float(wallet.balance) < 10:
                    step_decide = f"决策: 跳过 (余额不足: {float(wallet.balance) if wallet else 0})"
                    decision = "skip"
                else:
                    available = float(wallet.balance)
                    margin = available * (position_pct / 100)
                    notional = margin * leverage
                    quantity = notional / current_price

                    # 用品种管理器取整
                    from app.core.security import security_manager
                    quantity = float(security_manager.round_quantity_up(symbol, quantity))

                    # 计算止损止盈价格
                    if side == "buy":
                        sl_price = round(current_price * (1 - sl_pct / 100), 2)
                        tp_price = round(current_price * (1 + tp_pct / 100), 2)
                    else:
                        sl_price = round(current_price * (1 + sl_pct / 100), 2)
                        tp_price = round(current_price * (1 - tp_pct / 100), 2)

                    trade_action = {
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "leverage": leverage,
                        "price": current_price,
                        "stop_loss": sl_price,
                        "take_profit": tp_price,
                        "margin": round(margin, 2),
                        "notional": round(notional, 2),
                    }

                    step_decide = (
                        f"决策: 交易\n"
                        f"  方向: {side}, 交易对: {symbol}\n"
                        f"  数量: {quantity}, 杠杆: {leverage}x\n"
                        f"  保证金: ${margin:.2f} ({position_pct}% 仓位)\n"
                        f"  止损: ${sl_price} ({sl_pct}%), 止盈: ${tp_price} ({tp_pct}%)\n"
                        f"  触发新闻: {article.title_zh or article.title}"
                    )

                    # 通过 Pipeline 下单
                    from app.core.pipeline import get_pipeline
                    from app.models.position import Position, PositionStatus

                    pipeline = get_pipeline(user_id)

                    pos_result = await db.execute(
                        select(Position).where(
                            Position.user_id == user_id,
                            Position.status == PositionStatus.OPEN,
                        )
                    )
                    positions = pos_result.scalars().all()
                    open_positions = [
                        {"symbol": p.symbol, "side": p.side.value, "size": float(p.size)}
                        for p in positions
                    ]

                    result = await pipeline.submit_order(
                        db=db,
                        symbol=symbol,
                        side=side,
                        quantity=Decimal(str(quantity)),
                        leverage=leverage,
                        price=Decimal(str(current_price)),
                        stop_loss=Decimal(str(sl_price)),
                        take_profit=Decimal(str(tp_price)),
                        source="news",
                        note=f"[新闻交易] {alert.name}: {article.title_zh or article.title[:50]}",
                        available_balance=Decimal(str(available)),
                        total_equity=Decimal(str(wallet.total_equity)),
                        open_positions=open_positions,
                    )

                    if result.get("success"):
                        position_id = result.get("position_id")
                        decision = "trade"
                        step_decide += f"\n✅ 下单成功, 仓位 #{position_id}"
                        logger.info(
                            "[NewsMonitor] 新闻交易执行: %s %s %s qty=%s pos=#%s",
                            alert.name, side, symbol, quantity, position_id,
                        )
                    else:
                        decision = "skip"
                        error = result.get("error", "未知错误")
                        step_decide += f"\n❌ 下单失败: {error}"
                        logger.warning(
                            "[NewsMonitor] 新闻交易下单失败: %s → %s",
                            alert.name, error,
                        )

        except Exception as e:
            step_decide = f"决策: 交易异常 — {str(e)}"
            decision = "skip"
            logger.error("[NewsMonitor] trigger_alert trade error: %s", e)

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
        alert.last_triggered_at = datetime.utcnow()

        await db.flush()

        logger.info(
            "[NewsMonitor] 触发 Alert '%s' → decision=%s, NewsThinking #%d",
            alert.name,
            decision,
            thinking.id,
        )

        return thinking
