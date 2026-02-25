"""
FundingRateService 閳?鐠у嫰鍣剧拹鍦芳閺嶇绺鹃張宥呭
=======================================
娑撱儲鐗哥€佃鐖ｇ敮浣哥暔 U 閺堫兛缍呭鍝ョ敾閸氬牏瀹崇挧鍕櫨鐠愬湱宸奸張鍝勫煑

閼卞矁鐭?
1. 鐎规碍妞傞柌鍥肠閹碘偓閺堝姘﹂弰鎾愁嚠閻ㄥ嫯绁柌鎴ｅ瀭閻?(premiumIndex)
2. 閸愬懎鐡ㄧ紓鎾崇摠瑜版挸澧犵拹鍦芳 (娓氭稑鎮囧Ο鈥虫健鐎圭偞妞傜拠璇插絿)
3. 閹恒劑鈧礁鍩?Redis (娓氭稑澧犵粩顖涚叀閻?
4. 濮?8h 缂佹挾鐣? 閹殿偅寮块幍鈧張澶嬪瘮娴?閳?鐠侊紕鐣荤拹鍦暏 閳?閹碉綀鍨?閸忋儴澶?

鐢礁鐣ㄧ憴鍕灟:
- 缂佹挾鐣婚崨銊︽埂: 濮?8h (00:00, 08:00, 16:00 UTC)
- 鐠愬湱鏁?= 娴犳挷缍呴崥宥勭疅娴犲嘲鈧?鑴?鐠у嫰鍣剧拹鍦芳
- 閸氬秳绠熸禒宄扳偓?= 閹镐椒绮ㄩ弫浼村櫤 鑴?閺嶅洩顔囨禒閿嬬壐
- 濮濓綀鍨傞悳? 婢舵艾銇旀禒妯尖敄婢? 鐠愮喕鍨傞悳? 缁屽搫銇旀禒妯侯樋婢?
- 娴犲懎顕紒鎾剁暬閺冭泛鍩㈤幐浣规箒娴犳挷缍呴惃鍕暏閹撮攱鏁归崣?
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
# 閸愬懎鐡ㄧ紓鎾崇摠
# ============================================================

# {symbol: {markPrice, lastFundingRate, nextFundingTime, updated_at}}
_rate_cache: Dict[str, dict] = {}

REDIS_FUNDING_PREFIX = "autotrade:funding:"


class FundingRateService:
    """鐠у嫰鍣剧拹鍦芳闁插洭娉?+ 缂佹挾鐣婚張宥呭"""

    def __init__(self):
        self._client = BinanceClient()
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    # ----------------------------------------------------------
    # 閸氼垰濮?/ 閸嬫粍顒?
    # ----------------------------------------------------------

    async def start(self):
        """閸氼垰濮╃拹鍦芳闁插洭娉﹀顏嗗箚"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[FundingRate] 鐠愬湱宸奸柌鍥肠閺堝秴濮熷鎻掓儙閸?)

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
        logger.info("[FundingRate] 鐠愬湱宸奸柌鍥肠閺堝秴濮熷鎻掍粻濮?)

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        return self._redis

    # ----------------------------------------------------------
    # 闁插洭娉﹀顏嗗箚
    # ----------------------------------------------------------

    async def _loop(self):
        """
        娑撹鎯婇悳?
        - 濮?60s 闁插洭娉︽稉鈧▎鈩冨閺堝绔电粔宥堝瀭閻?
        - 濮ｅ繑顐煎Λ鈧弻銉︽Ц閸氾箑鍩屾禍?8h 缂佹挾鐣荤粣妤€褰?
        """
        last_settle_hour: Optional[int] = None

        while self._running:
            try:
                await self.fetch_all_rates()

                # 濡偓閺屻儲妲搁崥?8h 缂佹挾鐣婚弮鍫曟？ (00, 08, 16 UTC)
                now_utc = datetime.utcnow()
                current_hour = now_utc.hour
                if current_hour in (0, 8, 16) and current_hour != last_settle_hour:
                    # 閸︺劎绮ㄧ粻妤€鐨弮鍓佹畱閸?5 閸掑棝鎸撻崘鍛靶曢崣?
                    if now_utc.minute < 5:
                        await self._settle_all_users()
                        last_settle_hour = current_hour

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[FundingRate] 瀵邦亞骞嗗鍌氱埗: {e}")
                await asyncio.sleep(10)

    # ----------------------------------------------------------
    # 闁插洭娉? 閼惧嘲褰囬幍鈧張澶夋唉閺勬挸顕拹鍦芳
    # ----------------------------------------------------------

    async def fetch_all_rates(self):
        """
        娴犲骸绔电€瑰澹掗柌蹇氬箯閸欐牗澧嶉張澶夋唉閺勬挸顕拹鍦芳楠炲墎绱︾€?
        娴ｈ法鏁?MarketCollector.SYMBOLS 閸斻劍鈧浇骞忛崣鏍兇缂佺喎鍞寸敮浣侯潚
        """
        from app.services.market_collector import MarketCollector

        all_rates = await self._client.get_all_funding_rates()
        if not all_rates:
            return

        # 缁崵绮洪崘鍛畱鐢胶顫掗梿鍡楁値
        system_symbols = set(MarketCollector.SYMBOLS)

        now_iso = datetime.utcnow().isoformat() + "Z"

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

        # 閹恒劑鈧礁鍩?Redis
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
            logger.warning(f"[FundingRate] Redis 閹恒劑鈧礁銇戠拹? {e}")

        logger.debug(
            f"[FundingRate] 瀹稿弶娲块弬?{len(_rate_cache)} 娑擃亙姘﹂弰鎾愁嚠鐠愬湱宸?
        )

    # ----------------------------------------------------------
    # 缂佹挾鐣? 閹殿偅寮块幍鈧張澶屾暏閹磋渹绮ㄦ担宥呰嫙閹碉綀鍨?
    # ----------------------------------------------------------

    async def _settle_all_users(self):
        """
        8 鐏忓繑妞傜紒鎾剁暬 閳?閹殿偅寮块幍鈧張澶嬪瘮娴犳挾鏁ら幋宄拌嫙閹笛嗩攽鐠у嫰鍣剧拹鍦芳閹碉綀鍨?

        鐢礁鐣ㄧ憴鍕灟:
        - 鐠愬湱鏁?= 閹镐椒绮ㄩ弫浼村櫤 鑴?閺嶅洩顔囨禒?鑴?鐠у嫰鍣剧拹鍦芳
        - 濮濓綀鍨傞悳? 婢舵艾銇旈幍锝堝瀭(-), 缁屽搫銇旈崗銉ㄥ(+)
        - 鐠愮喕鍨傞悳? 婢舵艾銇旈崗銉ㄥ(+), 缁屽搫銇旈幍锝堝瀭(-)
        """
        logger.info("[FundingRate] 閳?瀵偓婵?8h 鐠у嫰鍣剧拹鍦芳缂佹挾鐣?..")

        async with AsyncSessionLocal() as db:
            try:
                from app.models.position import Position, PositionStatus, PositionSide
                from app.models.wallet import Wallet
                from app.models.wallet_transaction import WalletTransaction, TransactionType

                # 閺屻儴顕楅幍鈧張澶嬪ⅵ瀵偓閻ㄥ嫪绮ㄦ担?
                result = await db.execute(
                    select(Position).where(Position.status == PositionStatus.OPEN)
                )
                open_positions = result.scalars().all()

                if not open_positions:
                    logger.info("[FundingRate] 閺冪姵瀵旀禒? 鐠哄疇绻冪紒鎾剁暬")
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

                    # 閸氬秳绠熸禒宄扳偓?= 閺佷即鍣?鑴?閺嶅洩顔囨禒?
                    notional = pos.size * mark_price

                    # 鐠у嫰鍣剧拹鍦暏 (缂佹繂顕崐?
                    fee_amount = notional * funding_rate

                    # 閺傜懓鎮滈柅鏄忕帆:
                    # 濮濓綀鍨傞悳?閳?婢舵艾銇旀禒?(fee_amount 娑撶儤顒? 婢舵艾銇旈幍?, 缁屽搫銇旈弨?
                    # 鐠愮喕鍨傞悳?閳?缁屽搫銇旀禒? 婢舵艾銇旈弨?(fee_amount 娑撻缚绀?
                    if pos.side == PositionSide.LONG:
                        # 婢舵艾銇? 濮濓綀鍨傞悳鍥ㄦ閹碉綁鎸? 鐠愮喕鍨傞悳鍥ㄦ閺€鍫曟尪
                        wallet_delta = -fee_amount  # 濮濓綀鍨傞悳?閳?-濮?= 閹? 鐠愮喕鍨傞悳?閳?-鐠?= 閸?
                    else:
                        # 缁屽搫銇? 濮濓綀鍨傞悳鍥ㄦ閺€鍫曟尪, 鐠愮喕鍨傞悳鍥ㄦ閹碉綁鎸?
                        wallet_delta = fee_amount

                    # 閺囧瓨鏌婇柦鍗炲瘶
                    wallet = await db.get(Wallet, pos.user_id)
                    if not wallet:
                        continue

                    wallet.balance += wallet_delta

                    # 闂冨弶顒涙担娆擃杺娑撻缚绀?(閺嬩胶顏幆鍛枌)
                    if wallet.balance < 0:
                        wallet_delta -= wallet.balance  # 鐠嬪啯鏆?
                        wallet.balance = Decimal("0")

                    # 閺囧瓨鏌婃禒鎾茬秴缁鳖垵顓哥挧鍕櫨鐠愬湱鏁?(濮?瀹歌弓绮? 鐠?瀹稿弶鏁?
                    pos.total_funding_fee += (-wallet_delta)

                    # 閸愭瑥鍙嗗ù浣规寜
                    tx = WalletTransaction(
                        user_id=pos.user_id,
                        type=TransactionType.FUNDING.value,
                        amount=wallet_delta,
                        balance_after=wallet.balance,
                        related_position_id=pos.id,
                        note=(
                            f"鐠у嫰鍣剧拹鍦芳缂佹挾鐣? {pos.symbol} "
                            f"{'婢? if pos.side == PositionSide.LONG else '缁?} "
                            f"鐠愬湱宸?{float(funding_rate):.6f} "
                            f"閸氬秳绠?{float(notional):.2f}"
                        ),
                    )
                    db.add(tx)
                    total_settled += 1

                await db.commit()
                logger.info(
                    f"[FundingRate] 閴?缂佹挾鐣荤€瑰本鍨? {total_settled} 缁楁柧绮ㄦ担?
                )

            except Exception as e:
                await db.rollback()
                logger.error(f"[FundingRate] 閴?缂佹挾鐣诲鍌氱埗: {e}")

    # ----------------------------------------------------------
    # 閸忣剙绱?API: 鐠囪褰囩紓鎾崇摠
    # ----------------------------------------------------------

    @staticmethod
    def get_cached_rate(symbol: str) -> Optional[dict]:
        """閼惧嘲褰囬弻鎰唉閺勬挸顕惃鍕敶鐎涙绱︾€涙鍨傞悳?""
        return _rate_cache.get(symbol)

    @staticmethod
    def get_all_cached_rates() -> Dict[str, dict]:
        """閼惧嘲褰囬幍鈧張澶岀处鐎涙鍨傞悳?""
        return dict(_rate_cache)

    async def get_funding_info(self, symbol: str) -> Optional[dict]:
        """閼惧嘲褰囬崡鏇氶嚋娴溿倖妲楃€靛湱娈戠€瑰本鏆ｇ拹鍦芳娣団剝浼?(閸氼偄鍕鹃崠?"""
        data = await self._client.get_funding_rate(symbol)
        if not data:
            return None

        rate = float(data.get("lastFundingRate", 0))
        # 楠炴潙瀵?= 鐠愬湱宸?鑴?3 (濮ｅ繐銇? 鑴?365
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
            "direction": "婢舵艾銇旀禒妯垮瀭" if rate > 0 else "缁屽搫銇旀禒妯垮瀭" if rate < 0 else "闂嗘儼鍨傞悳?,
        }


# 閸忋劌鐪崡鏇氱伐
funding_rate_service = FundingRateService()
