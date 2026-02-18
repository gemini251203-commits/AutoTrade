"""
News Monitor
================
新闻关键词监控 + 触发引擎

职责:
- 加载活跃的 NewsAlert 规则
- 每条新闻到达时做关键词匹配
- 匹配成功 → 调用 AI 分析 → 可能触发交易
- 生成 NewsThinking 思考记录
"""

import logging
from datetime import datetime, timezone
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
    Phase 2 会实现完整的 AI 分析 + 自动交易。
    Phase 1 只做基本匹配和记录。
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
                datetime.now(timezone.utc)
                - alert.last_triggered_at.replace(tzinfo=timezone.utc)
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
        触发匹配的 Alert，创建 NewsThinking 记录
        
        Phase 1: 只记录，不自动交易
        Phase 2: 会集成 AI 分析 + AutoPilot 交易
        """
        # 创建思考记录 (Phase 1 基础版)
        thinking = NewsThinking(
            user_id=user_id,
            news_article_id=article.id,
            news_alert_id=alert.id,
            step_get_news=f"新闻: {article.title_zh or article.title}",
            step_analyze=f"分类: {article.news_category}, 情感: {article.sentiment} ({article.sentiment_score})",
            step_evaluate=f"规则 '{alert.name}' 匹配成功",
            step_decide="[Phase 1] 仅记录，等待 Phase 2 AI 分析",
            decision="watch",
        )
        db.add(thinking)
        
        # 更新 Alert 统计
        alert.triggered_count += 1
        alert.last_triggered_at = datetime.now(timezone.utc)
        
        await db.flush()
        
        logger.info(
            "[NewsMonitor] 触发 Alert '%s' → NewsThinking #%d",
            alert.name,
            thinking.id,
        )
        
        return thinking
