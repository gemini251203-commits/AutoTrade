"""
News Sentiment
================
情感分析 + AI翻译

职责:
- 基于 CryptoPanic 投票数据计算情感评分
- 使用现有 AI 模型翻译英文标题为中文
- 使用现有 AI 模型分类新闻到6大类
"""

import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 情感分析
# ============================================================

def analyze_sentiment(
    title: str,
    votes_positive: int,
    votes_negative: int,
) -> Tuple[str, float]:
    """
    基于投票数据计算情感评分
    
    Args:
        title: 新闻标题
        votes_positive: 正面投票数
        votes_negative: 负面投票数
    
    Returns:
        (sentiment, sentiment_score)
        sentiment: "positive" / "negative" / "neutral"
        sentiment_score: -1.0 ~ 1.0
    """
    total = votes_positive + votes_negative
    
    if total == 0:
        # 无投票时根据关键词简单判断
        return _keyword_sentiment(title)
    
    # 计算评分: (正 - 负) / 总
    score = (votes_positive - votes_negative) / total
    
    # 限制范围
    score = max(-1.0, min(1.0, score))
    
    if score > 0.2:
        return "positive", round(score, 3)
    elif score < -0.2:
        return "negative", round(score, 3)
    else:
        return "neutral", round(score, 3)


def _keyword_sentiment(title: str) -> Tuple[str, float]:
    """基于关键词的简单情感判断 (备用方案)"""
    title_lower = title.lower()
    
    positive_keywords = [
        "approval", "approved", "bullish", "surge", "rally", "pump",
        "breakout", "ath", "all-time high", "partnership", "launch",
        "adoption", "upgrade", "etf approved", "rate cut", "inflow",
    ]
    negative_keywords = [
        "crash", "dump", "bearish", "hack", "exploit", "ban",
        "lawsuit", "sec", "investigation", "fraud", "scam",
        "liquidation", "outflow", "rate hike", "delisted",
    ]
    
    pos_count = sum(1 for kw in positive_keywords if kw in title_lower)
    neg_count = sum(1 for kw in negative_keywords if kw in title_lower)
    
    if pos_count > neg_count:
        score = min(0.5, pos_count * 0.2)
        return "positive", score
    elif neg_count > pos_count:
        score = max(-0.5, -neg_count * 0.2)
        return "negative", score
    else:
        return "neutral", 0.0


# ============================================================
# AI 翻译
# ============================================================

async def translate_title(title_en: str) -> Optional[str]:
    """
    使用现有 AI 模型翻译英文标题为中文
    
    Args:
        title_en: 英文标题
    
    Returns:
        中文标题, 失败返回 None
    """
    try:
        from app.services.ai.providers import DeepSeekProvider, ChatMessage
        from app.core.config import settings
        
        provider = DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            model="deepseek-chat",
            timeout=15,
        )
        
        prompt = (
            "将以下加密货币新闻标题翻译成简洁的中文，"
            "只返回翻译结果，不要添加任何解释：\n\n"
            f"{title_en}"
        )
        
        response = await provider.chat(
            messages=[ChatMessage(role="user", content=prompt)],
            max_tokens=200,
            temperature=0.1,
        )
        
        if response and response.content:
            return response.content.strip().strip('"').strip("'")
        return None
        
    except Exception as e:
        logger.warning("[Sentiment] 翻译失败: %s", e)
        return None


# ============================================================
# AI 分类
# ============================================================

# 新闻分类: macro, etf, regulation, exchange, whale, project
CATEGORY_KEYWORDS = {
    "macro": [
        "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
        "cpi", "inflation", "gdp", "employment", "fomc", "powell",
        "treasury", "yield", "recession", "stimulus", "monetary policy",
    ],
    "etf": [
        "etf", "blackrock", "grayscale", "fidelity", "ark invest",
        "institutional", "fund", "inflow", "outflow", "spot etf",
    ],
    "regulation": [
        "sec", "cftc", "regulation", "regulatory", "compliance",
        "lawsuit", "court", "legal", "ban", "license", "framework",
        "congress", "legislation", "enforcement",
    ],
    "exchange": [
        "binance", "coinbase", "kraken", "listing", "delist",
        "exchange", "trading pair", "launch", "ipo",
    ],
    "whale": [
        "whale", "large transfer", "wallet", "dormant",
        "moved", "accumulation", "distribution",
    ],
    "project": [
        "upgrade", "fork", "mainnet", "testnet", "partnership",
        "vulnerability", "exploit", "hack", "protocol", "defi",
        "nft", "layer", "bridge", "airdrop",
    ],
}


async def classify_category(title: str) -> Optional[str]:
    """
    分类新闻到6大类
    
    优先使用关键词匹配 (速度快、免费)
    关键词无法匹配时使用 AI 分类
    
    Args:
        title: 新闻标题 (英文)
    
    Returns:
        分类: macro/etf/regulation/exchange/whale/project 或 None
    """
    title_lower = title.lower()
    
    # 关键词匹配 (按优先级排序)
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw in title_lower)
        if match_count > 0:
            scores[category] = match_count
    
    if scores:
        # 返回匹配最多的分类
        return max(scores, key=scores.get)
    
    # 没有匹配到关键词，尝试 AI 分类 (仅在 DeepSeek 配置时)
    try:
        from app.core.config import settings
        if not settings.deepseek_api_key:
            return None
        
        from app.services.ai.providers import DeepSeekProvider, ChatMessage
        
        provider = DeepSeekProvider(
            api_key=settings.deepseek_api_key,
            model="deepseek-chat",
            timeout=10,
        )
        
        prompt = (
            "Classify this crypto news headline into exactly ONE category.\n"
            "Categories: macro, etf, regulation, exchange, whale, project\n"
            "Reply with ONLY the category name, nothing else.\n\n"
            f"Headline: {title}"
        )
        
        response = await provider.chat(
            messages=[ChatMessage(role="user", content=prompt)],
            max_tokens=20,
            temperature=0.0,
        )
        
        if response and response.content:
            category = response.content.strip().lower()
            if category in CATEGORY_KEYWORDS:
                return category
        
        return None
        
    except Exception as e:
        logger.warning("[Sentiment] AI分类失败: %s", e)
        return None
