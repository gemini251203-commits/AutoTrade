"""
FundingRateService — 资金费率核心服务
=======================================
严格对标币安 U 本位永续合约资金费率机制

职责:
1. 定时采集所有交易对的资金费率 (premiumIndex)
2. 内存缓存当前费率 (供各模块实时读取)
3. 推送到 Redis (供前端查看)
4. 每 8h 结算: 扫描所有持仓 → 计算费用 → 扣费/入账

币安规则:
- 结算周期: 每 8h (00:00, 08:00, 16:00 UTC)
- 费用 = 仓位名义价值 × 资金费率
- 名义价值 = 持仓数量 × 标记价格
- 正费率: 多头付空头; 负费率: 空头付多头
- 仅对结算时刻持有仓位的用户收取
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import redis.asyncio as aioredis
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.exchange import BinanceClient


# ============================================================
# 内存缓存
# ============================================================

# {symbol: {markPrice, lastFundingRate, nextFundingTime, updated_at}}
_rate_cache: Dict[str, dict] = {}

REDIS_FUNDING_PREFIX = "autotrade:funding:"


class FundingRateService:
    """资金费率采集 + 结算服务"""

    def __init__(self):
        self._client = BinanceClient()
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ----------------------------------------------------------
    # 启动 / 停止
    # ----------------------------------------------------------

    async def start(self):
        """启动费率采集循环"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[FundingRate] 费率采集服务已启动")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("[FundingRate] 费率采集服务已停止")

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        return self._redis

    # ----------------------------------------------------------
    # 采集循环
    # ----------------------------------------------------------

    async def _loop(self):
        """
        主循环:
        - 每 60s 采集一次所有币种费率
        - 每次检查是否到了 8h 结算窗口
        """
        last_settle_hour: Optional[int] = None

        while self._running:
            try:
                await self.fetch_all_rates()

                # 检查是否 8h 结算时间 (00, 08, 16 UTC)
                now_utc = datetime.now(timezone.utc)
                current_hour = now_utc.hour
                if current_hour in (0, 8, 16) and current_hour != last_settle_hour:
                    # 在结算小时的前 5 分钟内触发
                    if now_utc.minute < 5:
                        await self._settle_all_users()
                        last_settle_hour = current_hour

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[FundingRate] 循环异常: {e}")
                await asyncio.sleep(10)

    # ----------------------------------------------------------
    # 采集: 获取所有交易对费率
    # ----------------------------------------------------------

    async def fetch_all_rates(self):
        """
        从币安批量获取所有交易对费率并缓存
        使用 MarketCollector.SYMBOLS 动态获取系统内币种
        """
        from app.services.market_collector import MarketCollector

        all_rates = await self._client.get_all_funding_rates()
        if not all_rates:
            return

        # 系统内的币种集合
        system_symbols = set(MarketCollector.SYMBOLS)

        now_iso = datetime.utcnow().isoformat()

        for rate_data in all_rates:
            symbol = rate_data.get("symbol", "")
            if symbol not in system_symbols:
                continue

            _rate_cache[symbol] = {
                "symbol": symbol,
                "markPrice": rate_data.get("markPrice", "0"),
                "lastFundingRate": rate_data.get("lastFundingRate", "0"),
                "nextFundingTime": rate_data.get("nextFundingTime", 0),
                "updated_at": now_iso,
            }

        # 推送到 Redis
        try:
            r = await self._get_redis()
            for symbol, data in _rate_cache.items():
                key = f"{REDIS_FUNDING_PREFIX}{symbol}"
                await r.hset(key, mapping={
                    "symbol": symbol,
                    "markPrice": data["markPrice"],
                    "fundingRate": data["lastFundingRate"],
                    "nextFundingTime": str(data["nextFundingTime"]),
                    "updated_at": data["updated_at"],
                })
                await r.expire(key, 300)
        except Exception as e:
            logger.warning(f"[FundingRate] Redis 推送失败: {e}")

        logger.debug(
            f"[FundingRate] 已更新 {len(_rate_cache)} 个交易对费率"
        )

    # ----------------------------------------------------------
    # 结算: 扫描所有用户仓位并扣费
    # ----------------------------------------------------------

    async def _settle_all_users(self):
        """
        8 小时结算 — 扫描所有持仓用户并执行资金费率扣费

        币安规则:
        - 费用 = 持仓数量 × 标记价 × 资金费率
        - 正费率: 多头扣费(-), 空头入账(+)
        - 负费率: 多头入账(+), 空头扣费(-)
        """
        logger.info("[FundingRate] ⏰ 开始 8h 资金费率结算...")

        async with AsyncSessionLocal() as db:
            try:
                from app.models.position import Position, PositionStatus, PositionSide
                from app.models.wallet import Wallet
                from app.models.wallet_transaction import WalletTransaction, TransactionType

                # 查询所有打开的仓位
                result = await db.execute(
                    select(Position).where(Position.status == PositionStatus.OPEN)
                )
                open_positions = result.scalars().all()

                if not open_positions:
                    logger.info("[FundingRate] 无持仓, 跳过结算")
                    return

                total_settled = 0
                for pos in open_positions:
                    rate_info = _rate_cache.get(pos.symbol)
                    if not rate_info:
                        continue

                    try:
                        mark_price = Decimal(rate_info["markPrice"])
                        funding_rate = Decimal(rate_info["lastFundingRate"])
                    except Exception:
                        continue

                    if funding_rate == 0:
                        continue

                    # 名义价值 = 数量 × 标记价
                    notional = pos.size * mark_price

                    # 资金费用 (绝对值)
                    fee_amount = notional * funding_rate

                    # 方向逻辑:
                    # 正费率 → 多头付 (fee_amount 为正, 多头扣), 空头收
                    # 负费率 → 空头付, 多头收 (fee_amount 为负)
                    if pos.side == PositionSide.LONG:
                        # 多头: 正费率时扣钱, 负费率时收钱
                        wallet_delta = -fee_amount  # 正费率 → -正 = 扣; 负费率 → -负 = 加
                    else:
                        # 空头: 正费率时收钱, 负费率时扣钱
                        wallet_delta = fee_amount

                    # 更新钱包
                    wallet = await db.get(Wallet, pos.user_id)
                    if not wallet:
                        continue

                    wallet.balance += wallet_delta

                    # 防止余额为负 (极端情况)
                    if wallet.balance < 0:
                        wallet_delta -= wallet.balance  # 调整
                        wallet.balance = Decimal("0")

                    # 更新仓位累计资金费用 (正=已付, 负=已收)
                    pos.accumulated_funding_fee += (-wallet_delta)

                    # 写入流水
                    tx = WalletTransaction(
                        user_id=pos.user_id,
                        type=TransactionType.FUNDING.value,
                        amount=wallet_delta,
                        balance_after=wallet.balance,
                        related_position_id=pos.id,
                        note=(
                            f"资金费率结算: {pos.symbol} "
                            f"{'多' if pos.side == PositionSide.LONG else '空'} "
                            f"费率={float(funding_rate):.6f} "
                            f"名义={float(notional):.2f}"
                        ),
                    )
                    db.add(tx)
                    total_settled += 1

                await db.commit()
                logger.info(
                    f"[FundingRate] ✅ 结算完成: {total_settled} 笔仓位"
                )

            except Exception as e:
                await db.rollback()
                logger.error(f"[FundingRate] ❌ 结算异常: {e}")

    # ----------------------------------------------------------
    # 公开 API: 读取缓存
    # ----------------------------------------------------------

    @staticmethod
    def get_cached_rate(symbol: str) -> Optional[dict]:
        """获取某交易对的内存缓存费率"""
        return _rate_cache.get(symbol)

    @staticmethod
    def get_all_cached_rates() -> Dict[str, dict]:
        """获取所有缓存费率"""
        return dict(_rate_cache)

    async def get_funding_info(self, symbol: str) -> Optional[dict]:
        """获取单个交易对的完整费率信息 (含年化)"""
        data = await self._client.get_funding_rate(symbol)
        if not data:
            return None

        rate = float(data.get("lastFundingRate", 0))
        # 年化 = 费率 × 3 (每天) × 365
        annualized = rate * 3 * 365 * 100

        next_time = data.get("nextFundingTime", 0)
        if next_time:
            remaining_ms = next_time - int(datetime.utcnow().timestamp() * 1000)
            remaining_min = max(0, remaining_ms // 60000)
        else:
            remaining_min = 0

        return {
            "symbol": data["symbol"],
            "markPrice": data["markPrice"],
            "fundingRate": data["lastFundingRate"],
            "fundingRatePct": f"{rate * 100:.4f}%",
            "annualizedPct": f"{annualized:.2f}%",
            "nextFundingTime": next_time,
            "remainingMinutes": remaining_min,
            "direction": "多头付费" if rate > 0 else "空头付费" if rate < 0 else "零费率",
        }


# 全局单例
funding_rate_service = FundingRateService()
