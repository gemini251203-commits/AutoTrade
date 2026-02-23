"""
News Models
================
新闻数据模型

表:
- news_articles: 新闻文章 (抓取+情感分析)
- news_alerts: 新闻监控规则 (关键词+交易配置)
- news_thinkings: AI 新闻思考记录 (全链路审计)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, Boolean, DateTime,
    ForeignKey, Index, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ============================================================
# 新闻分类枚举值 (用于 news_category 字段)
# ============================================================
# macro      - 宏观经济 (美联储利率、CPI、就业)
# etf        - ETF/机构 (ETF批准、机构买入)
# regulation - 监管政策 (SEC、各国立法)
# exchange   - 交易所 (上币、下架、被黑)
# whale      - 巨鲸动向 (大额转账、钱包变动)
# project    - 项目/技术 (升级、漏洞、合作)


class NewsArticle(Base):
    """
    新闻文章

    来源: CryptoPanic / Binance 公告
    每条新闻包含原始英文标题、AI翻译中文标题、情感评分
    """
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ============ 来源标识 ============
    source: Mapped[str] = mapped_column(
        String(50),
        comment="来源: cryptocompare / cryptopanic / binance",
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        comment="外部ID (去重用)",
    )

    # ============ 内容 ============
    title: Mapped[str] = mapped_column(
        String(500),
        comment="英文原始标题",
    )
    title_zh: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="AI翻译中文标题",
    )
    url: Mapped[str] = mapped_column(
        String(1000),
        comment="原文链接",
    )

    # ============ 分类 & 情感 ============
    currencies: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment='关联币种 ["BTC","ETH"]',
    )
    news_category: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="分类: macro/etf/regulation/exchange/whale/project",
    )
    sentiment: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="情感: positive/negative/neutral",
    )
    sentiment_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        default=0.0,
        comment="情感评分 -1.0 ~ 1.0",
    )
    importance: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        default="medium",
        comment="重要性: high/medium/low",
    )

    # ============ CryptoPanic 投票 ============
    votes_positive: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        comment="正面投票数",
    )
    votes_negative: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        comment="负面投票数",
    )

    # ============ 原始数据 ============
    raw_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="API原始返回数据",
    )

    # ============ 时间 ============
    published_at: Mapped[datetime] = mapped_column(
        DateTime,
        comment="新闻发布时间",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        comment="入库时间",
    )

    __table_args__ = (
        Index("ix_news_articles_published", "published_at"),
        Index("ix_news_articles_source", "source"),
    )

    def __repr__(self):
        cat = f"[{self.news_category}]" if self.news_category else ""
        sent = self.sentiment or "?"
        return f"<NewsArticle {cat} {sent} {self.title[:40]}>"


class NewsAlert(Base):
    """
    新闻监控规则

    用户定义关键词 + 币种 + 交易规则
    支持 "通知" 和 "自动交易" 两种动作
    支持可靠性标记 (用户可开关)
    """
    __tablename__ = "news_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )

    # ============ 规则定义 ============
    name: Mapped[str] = mapped_column(
        String(100),
        comment="规则名称",
    )
    keywords: Mapped[dict] = mapped_column(
        JSON,
        comment='关键词列表 ["降息","rate cut"]',
    )
    news_categories: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment='监控的新闻分类 ["macro","etf"]',
    )
    currencies: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment='关注币种 ["BTC"]',
    )
    sentiment_filter: Mapped[str] = mapped_column(
        String(10),
        default="any",
        comment="情感过滤: any/positive/negative",
    )

    # ============ 动作配置 ============
    action: Mapped[str] = mapped_column(
        String(10),
        default="notify",
        comment="动作: notify/trade",
    )
    trade_side: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="交易方向: buy/sell",
    )
    trade_symbol: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="交易对, 如 BTCUSDT",
    )
    trade_position_pct: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="仓位百分比 (最大15%)",
    )
    trade_leverage: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="杠杆倍数 (最大20x)",
    )
    trade_stop_loss_pct: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="止损百分比",
    )
    trade_take_profit_pct: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="止盈百分比",
    )

    # ============ 状态 & 可靠性 ============
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="是否启用",
    )
    is_reliable: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="用户标记: 此类新闻是否可靠",
    )
    reliability_note: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="可靠性备注 (为什么关闭/开启)",
    )

    # ============ 统计 ============
    triggered_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="触发次数",
    )
    win_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="盈利次数",
    )
    loss_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="亏损次数",
    )
    total_pnl: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        comment="总盈亏 (USDT)",
    )
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="最后触发时间",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_news_alerts_user", "user_id", "is_active"),
    )

    def __repr__(self):
        status = "✅" if self.is_active else "⏸️"
        return f"<NewsAlert {status} {self.name}>"


class NewsThinking(Base):
    """
    AI 新闻思考记录

    记录 AI 从看到新闻到做出决策的全链路思考过程:
    ① 获取新闻 (step_get_news)
    ② 分析影响 (step_analyze)
    ③ 评估可靠性 (step_evaluate)
    ④ 决策 (step_decide)
    ⑤ 交易后反思 (ai_reflection)
    """
    __tablename__ = "news_thinkings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
    )
    news_article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.id"),
        index=True,
        comment="关联新闻",
    )
    news_alert_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("news_alerts.id"),
        nullable=True,
        comment="关联监控规则",
    )

    # ============ 思考链路 ============
    step_get_news: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="① AI获取新闻: 原文摘要",
    )
    step_analyze: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="② AI分析: 可能的影响方向和程度",
    )
    step_evaluate: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="③ AI评估: 可靠性+历史类似新闻表现",
    )
    step_decide: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="④ AI决策: 是否交易+理由",
    )

    # ============ 决策结果 ============
    decision: Mapped[str] = mapped_column(
        String(10),
        default="skip",
        comment="决策: trade/skip/watch",
    )
    trade_action: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="交易动作 {side, symbol, amount, ...}",
    )

    # ============ 交易关联 (如果执行了交易) ============
    position_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="关联仓位ID (交易后回填)",
    )
    trade_result: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="交易结果: win/loss/breakeven (平仓后回填)",
    )
    trade_pnl: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="盈亏金额 USDT (平仓后回填)",
    )

    # ============ AI 反思 ============
    ai_reflection: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI反思: 新闻影响是否准确+经验教训",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_news_thinkings_user", "user_id", "created_at"),
        Index("ix_news_thinkings_article", "news_article_id"),
    )

    def __repr__(self):
        emoji = {"trade": "📊", "skip": "⏭️", "watch": "👀"}.get(self.decision, "?")
        return f"<NewsThinking {emoji} {self.decision}>"
