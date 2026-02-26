"""
News Crawler
================
CryptoCompare 新闻抓取器

职责:
- 定时轮询 CryptoCompare News API (每5分钟)
- 解析新闻数据并存入 news_articles 表
- 自动去重 (external_id)
- 调用情感分析 + AI翻译
"""

import asyncio
import hashlib
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


# CryptoCompare News API 配置
CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"
POLL_INTERVAL = 300  # 5 分钟 (免费版 100k 请求/月, 5min 间隔 ≈ 8640/月)


class NewsCrawler:
    """
    CryptoCompare 新闻爬虫
    
    用法:
        crawler = NewsCrawler(api_key="xxx")
        await crawler.start()
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "cryptocompare_api_key", "")
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """启动定时抓取"""
        if self._running:
            logger.warning("[NewsCrawler] 已在运行中")
            return
        
        if not self.api_key:
            logger.error("[NewsCrawler] 缺少 CryptoCompare API Key，无法启动")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[NewsCrawler] 已启动 (CryptoCompare)，每 %ds 轮询一次", POLL_INTERVAL)
    
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
        raw_posts = await self._fetch_cryptocompare()
        if not raw_posts:
            return
        
        saved_count = 0
        new_articles = []
        async with AsyncSessionLocal() as db:
            for post in raw_posts:
                try:
                    article = await self._parse_and_save(db, post)
                    if article:
                        saved_count += 1
                        new_articles.append(article)
                except Exception as e:
                    logger.warning("[NewsCrawler] 解析失败: %s", e)
            
            if saved_count > 0:
                await db.commit()
                logger.info("[NewsCrawler] 新增 %d 条新闻", saved_count)
            
            # 新闻监控: 检查新文章是否匹配用户的Alert规则
            if new_articles:
                try:
                    from app.services.news.monitor import NewsMonitor
                    monitor = NewsMonitor()
                    for article in new_articles:
                        matched_alerts = await monitor.check_article(db, article)
                        for alert in matched_alerts:
                            try:
                                await monitor.trigger_alert(
                                    db, article, alert, user_id=alert.user_id
                                )
                            except Exception as e:
                                logger.error(
                                    "[NewsCrawler] 触发Alert失败 '%s': %s",
                                    alert.name, e,
                                )
                    await db.commit()
                except Exception as e:
                    logger.error("[NewsCrawler] 新闻监控检查失败: %s", e)
    
    async def _fetch_cryptocompare(self) -> List[Dict[str, Any]]:
        """调用 CryptoCompare News API"""
        from app.core.network import net_manager
        
        params = {
            "api_key": self.api_key,
            "lang": "EN",
            "sortOrder": "latest",
        }
        
        try:
            async with net_manager.get_client(timeout=15.0) as client:
                resp = await client.get(CRYPTOCOMPARE_NEWS_URL, params=params)
                if resp.status_code != 200:
                    logger.error(
                        "[NewsCrawler] CryptoCompare API 返回 %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return []
                
                data = resp.json()
                
                # CryptoCompare 返回格式: {"Type": 100, "Data": [...]}
                if data.get("Type") != 100:
                    msg = data.get("Message", "Unknown error")
                    logger.error("[NewsCrawler] CryptoCompare API 错误: %s", msg)
                    return []
                
                results = data.get("Data", [])
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
        # CryptoCompare 的 id 字段
        raw_id = post.get("id")
        if raw_id:
            external_id = str(raw_id)
        else:
            # 备用: 用 title + published_on 的 hash
            title_raw = post.get("title", "")
            pub = str(post.get("published_on", ""))
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
        
        # URL
        url = post.get("url") or post.get("guid") or ""
        
        # 发布时间 (CryptoCompare 用 Unix 时间戳)
        published_on = post.get("published_on", 0)
        try:
            published_at = datetime.fromtimestamp(published_on, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            published_at = datetime.now(timezone.utc)
        
        # 提取关联币种 (CryptoCompare 的 categories 字段包含币种)
        currencies = []
        categories_str = post.get("categories", "")
        if categories_str:
            # CryptoCompare categories 格式: "BTC|ETH|Trading|Technology"
            for cat in categories_str.split("|"):
                cat = cat.strip().upper()
                # 常见加密货币代码 (3-5 字符全大写)
                if len(cat) <= 5 and cat.isalpha() and cat in _KNOWN_CURRENCIES:
                    currencies.append(cat)
        
        # 来源 (截断到20字符, 数据库列限制)
        source_info = post.get("source_info", {}) or {}
        source_name = (source_info.get("name", "cryptocompare") or "cryptocompare")[:20]
        
        # CryptoCompare 没有投票数据, 统一为 0
        votes_positive = 0
        votes_negative = 0
        
        # 情感分析 (无投票时会走关键词分析)
        sentiment, sentiment_score = analyze_sentiment(
            title, votes_positive, votes_negative
        )
        
        # AI 翻译标题 (仅在 DeepSeek API Key 配置时)
        title_zh = None
        if settings.deepseek_api_key:
            title_zh = await translate_title(title)
        
        # 分类 (关键词匹配, 无需 AI)
        news_category = await classify_category(title)
        
        # 判断重要性
        importance = self._assess_importance(
            votes_positive, votes_negative, news_category
        )
        
        # 创建记录
        article = NewsArticle(
            source=source_name,
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
        
        # 根据投票判断 (CryptoCompare 没投票, 默认 low/medium)
        if total_votes >= 10:
            return "high"
        if total_votes >= 3:
            return "medium"
        return "low"


# 常见加密货币代码 (用于从 CryptoCompare categories 提取币种)
_KNOWN_CURRENCIES = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "LINK", "MATIC", "UNI", "ATOM", "LTC", "FIL",
    "APT", "ARB", "OP", "SUI", "SEI", "TIA", "NEAR",
    "SHIB", "PEPE", "BONK", "WIF", "MEME",
    "USDT", "USDC", "DAI", "BUSD",
    "AAVE", "MKR", "CRV", "SNX", "COMP",
    "FTM", "ALGO", "XLM", "VET", "EOS", "TRX", "HBAR",
}
