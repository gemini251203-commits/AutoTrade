"""
Trend Analysis Scheduler
=========================
定时自动运行趋势分析 (每日一次)

启动后每 24 小时自动:
1. 查询所有活跃的 TrendScheme
2. 对每个方案执行趋势分析
3. 缓存结果到 TrendScheme.last_result
4. 写入 TrendSnapshot 历史记录
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.trend_scheme import TrendScheme, TrendSnapshot
from app.services.quant.trend_analyzer import TrendAnalyzer


logger = logging.getLogger(__name__)

# 默认分析的交易对
DEFAULT_SYMBOLS = ["BTCUSDT"]

# 分析间隔 (秒): 24 小时
ANALYSIS_INTERVAL = 24 * 60 * 60

# 启动后首次分析的延迟 (秒): 30 秒
INITIAL_DELAY = 30


class TrendScheduler:
    """趋势分析定时调度器"""

    def __init__(self):
        self._running = False
        self._task = None

    async def start(self):
        """启动定时调度"""
        if self._running:
            logger.warning("[TrendScheduler] Already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[TrendScheduler] Started (interval=%dh)", ANALYSIS_INTERVAL // 3600)

    async def stop(self):
        """停止调度"""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[TrendScheduler] Stopped")

    async def _loop(self):
        """主循环"""
        # 首次延迟，等后台服务就绪
        await asyncio.sleep(INITIAL_DELAY)
        logger.info("[TrendScheduler] Initial run starting...")

        while self._running:
            try:
                await self._run_all()
            except Exception as e:
                logger.error("[TrendScheduler] Error in analysis cycle: %s", e)

            # 等待下一次
            logger.info(
                "[TrendScheduler] Next run in %d hours",
                ANALYSIS_INTERVAL // 3600,
            )
            await asyncio.sleep(ANALYSIS_INTERVAL)

    async def _run_all(self):
        """执行一轮: 所有活跃方案 × 所有交易对"""
        async with AsyncSessionLocal() as db:
            # 查询所有活跃方案 (所有用户)
            result = await db.execute(
                select(TrendScheme).where(TrendScheme.is_active == True)  # noqa
            )
            schemes = result.scalars().all()

            if not schemes:
                logger.info("[TrendScheduler] No active schemes, skipping")
                return

            logger.info(
                "[TrendScheduler] Running %d active scheme(s)...",
                len(schemes),
            )

            for scheme in schemes:
                for symbol in DEFAULT_SYMBOLS:
                    try:
                        await self._analyze_one(db, scheme, symbol)
                    except Exception as e:
                        logger.error(
                            "[TrendScheduler] Failed: scheme=%s symbol=%s err=%s",
                            scheme.name, symbol, e,
                        )

            await db.commit()
            logger.info("[TrendScheduler] Analysis cycle complete")

    async def _analyze_one(
        self,
        db,
        scheme: TrendScheme,
        symbol: str,
    ):
        """分析单个方案 + 单个交易对"""
        # 获取 K 线
        from app.core.network import net_manager

        analyzer = TrendAnalyzer()
        config = analyzer.parse_yaml(scheme.config_yaml)
        interval = config.get("interval", "1h")

        async with net_manager.get_client(timeout=15.0) as client:
            resp = await client.get(
                "https://fapi.binance.com/fapi/v1/klines",
                params={
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "limit": 200,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "[TrendScheduler] K-line fetch failed: %s %s → %d",
                    symbol, interval, resp.status_code,
                )
                return

            raw = resp.json()
            klines = [
                {
                    "open_time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                }
                for k in raw
            ]

        # 运行分析
        trend_result = analyzer.analyze(config, klines, symbol=symbol)

        # 更新缓存
        scheme.last_result = trend_result.to_dict()
        scheme.last_run_at = datetime.now(timezone.utc)

        # 写入快照
        snapshot = TrendSnapshot(
            scheme_id=scheme.id,
            user_id=scheme.user_id,
            symbol=symbol,
            direction=trend_result.direction,
            direction_score=trend_result.direction_score,
            strength=trend_result.strength,
            strength_score=trend_result.strength_score,
            volatility=trend_result.volatility,
            momentum=trend_result.momentum,
            regime=trend_result.regime,
            confidence=trend_result.confidence,
            suitable_strategies=trend_result.suitable_strategies,
            result_json=trend_result.to_dict(),
        )
        db.add(snapshot)

        logger.info(
            "[TrendScheduler] ✅ %s | %s → %s (%s) confidence=%.0f%%",
            scheme.name,
            symbol,
            trend_result.regime,
            trend_result.direction,
            trend_result.confidence,
        )


# 全局单例
trend_scheduler = TrendScheduler()
