"""
News Crawler
================
CryptoPanic 新闻抓取器

职责:
- 定时轮询 CryptoPanic API (每60秒)
- 解析新闻数据并存入 news_articles 表
- 自动去重 (external_id)
- 调用情感分析 + AI翻译
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.news import NewsArticle
from app.core.config import settings

from .sentiment import analyze_sentiment, translate_title, classify_category


logger = logging.getLogger(__name__)


# CryptoPanic API 配置
CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/developer/v2/posts/"
POLL_INTERVAL = 60  # 秒


class NewsCrawler:
    """
    CryptoPanic 新闻爬虫
    
    用法:
        crawler = NewsCrawler(api_key="xxx")
        await crawler.start()
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "cryptopanic_api_key", "")
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动定时抓取"""
        if self._running:
            logger.warning("[NewsCrawler] 已在运行中")
            return
        
        if not self.api_key:
            logger.error("[NewsCrawler] 缺少 CryptoPanic API Key，无法启动")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[NewsCrawler] 已启动，每 %ds 轮询一次", POLL_INTERVAL)
    
    async def stop(self):
        """停止抓取"""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[NewsCrawler] 已停止")
    
    async def _poll_loop(self):
        """轮询主循环"""
        while self._running:
            try:
                await self._fetch_and_save()
            except Exception as e:
                logger.error("[NewsCrawler] 抓取失败: %s", e)
            await asyncio.sleep(POLL_INTERVAL)
    
    async def _fetch_and_save(self):
        """抓取并保存新闻"""
        raw_posts = await self._fetch_cryptopanic()
        if not raw_posts:
            return
        
        saved_count = 0
        async with AsyncSessionLocal() as db:
            for post in raw_posts:
                try:
                    article = await self._parse_and_save(db, post)
                    if article:
                        saved_count += 1
                except Exception as e:
                    logger.warning("[NewsCrawler] 解析失败: %s", e)
            
            if saved_count > 0:
                await db.commit()
                logger.info("[NewsCrawler] 新增 %d 条新闻", saved_count)
    
    async def _fetch_cryptopanic(self) -> List[Dict[str, Any]]:
        """调用 CryptoPanic API"""
        from app.core.network import net_manager
        
        params = {
            "auth_token": self.api_key,
            "kind": "news",
            "public": "true",
        }
        
        try:
            async with net_manager.get_client(timeout=15.0) as client:
                resp = await client.get(CRYPTOPANIC_API_URL, params=params)
                if resp.status_code != 200:
                    logger.error(
                        "[NewsCrawler] API 返回 %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return []
                
                data = resp.json()
                results = data.get("results", [])
                logger.debug("[NewsCrawler] 获取 %d 条原始新闻", len(results))
                return results
                
        except Exception as e:
            logger.error("[NewsCrawler] 请求异常: %s", e)
            return []
    
    async def _parse_and_save(
        self,
        db: AsyncSession,
        post: Dict[str, Any],
    ) -> Optional[NewsArticle]:
        """解析单条新闻并保存 (去重)"""
        # v2 API 可能没有 id 字段，用 title+published_at 生成唯一 ID
        import hashlib
        raw_id = post.get("id")
        if raw_id:
            external_id = str(raw_id)
        else:
            # 用 title + published_at 的 hash 作为 external_id
            title_raw = post.get("title", "")
            pub = post.get("published_at", "")
            hash_input = f"{title_raw}|{pub}"
            external_id = hashlib.md5(hash_input.encode()).hexdigest()
        
        if not external_id:
            return None
        
        # 去重检查
        existing = await db.execute(
            select(NewsArticle).where(
                NewsArticle.external_id == external_id
            )
        )
        if existing.scalar_one_or_none():
            return None
        
        # 解析基础字段
        title = post.get("title", "").strip()
        if not title:
            return None
        
        # url: v2 可能没有, 用 CryptoPanic 搜索链接
        url = post.get("url") or post.get("source_url") or ""
        if not url and title:
            url = f"https://cryptopanic.com/news/click/{external_id[:8]}/"
        
        published_str = post.get("published_at", "")
        
        # 解析发布时间
        try:
            published_at = datetime.fromisoformat(
                published_str.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            published_at = datetime.now(timezone.utc)
        
        # 提取关联币种 (v2 可能没有 currencies 字段)
        currencies = []
        for curr in post.get("currencies", []) or []:
            if isinstance(curr, dict):
                code = curr.get("code", "")
            else:
                code = str(curr)
            if code:
                currencies.append(code)
        
        # CryptoPanic 投票数据 (v2 可能没有)
        votes = post.get("votes") or {}
        votes_positive = (
            votes.get("positive", 0)
            + votes.get("important", 0)
            + votes.get("liked", 0)
            + votes.get("saved", 0)
        )
        votes_negative = (
            votes.get("negative", 0)
            + votes.get("disliked", 0)
            + votes.get("toxic", 0)
        )
        
        # 情感分析
        sentiment, sentiment_score = analyze_sentiment(
            title, votes_positive, votes_negative
        )
        
        # AI 翻译标题 + 分类 (仅在 DeepSeek API Key 配置时)
        title_zh = None
        if settings.deepseek_api_key:
            title_zh = await translate_title(title)
        
        # 分类 (优先关键词匹配，无需 AI)
        news_category = await classify_category(title)
        
        # 判断重要性
        importance = self._assess_importance(
            votes_positive, votes_negative, news_category
        )
        
        # 创建记录
        article = NewsArticle(
            source="cryptopanic",
            external_id=external_id,
            title=title,
            title_zh=title_zh,
            url=url,
            published_at=published_at,
            currencies=currencies if currencies else None,
            news_category=news_category,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            importance=importance,
            votes_positive=votes_positive,
            votes_negative=votes_negative,
            raw_data=post,
        )
        db.add(article)
        await db.flush()
        
        logger.info(
            "[NewsCrawler] 新增: [%s] %s | %s | %.2f",
            news_category or "?",
            title[:50],
            sentiment,
            sentiment_score,
        )
        return article
    
    @staticmethod
    def _assess_importance(
        votes_positive: int,
        votes_negative: int,
        news_category: Optional[str],
    ) -> str:
        """评估新闻重要性"""
        total_votes = votes_positive + votes_negative
        
        # 宏观经济和 ETF 默认重要
        if news_category in ("macro", "etf"):
            return "high"
        
        # 监管类中等重要
        if news_category == "regulation":
            return "high" if total_votes >= 5 else "medium"
        
        # 根据投票判断
        if total_votes >= 10:
            return "high"
        if total_votes >= 3:
            return "medium"
        return "low"
