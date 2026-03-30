"""
Wake Monitor — AI 自主唤醒条件监控器
==========================================
让 AI Agent 在分析结束后自主设定唤醒条件,
系统后台持续监控, 条件满足时立即唤醒 Agent。

设计:
- 条件存储在 Redis (agent 停止后条件自然失效)
- 条件采用 AND 逻辑: 所有条件都满足才触发
- MarketCollector 已推送价格到 Redis, 零额外 API 调用
- 固定间隔轮询照常运行, 事件唤醒作为额外加速机制

条件类型:
- price_above: 价格突破上方 (BTC > 88000)
- price_below: 价格跌破下方 (BTC < 82000)  
- change_pct:  价格离基准变化超过阈值 (BTC ±2%)
"""

import json
import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import redis.asyncio as aioredis
from loguru import logger

from app.core.config import settings
from app.core.time_utils import utc_now


# Redis key 前缀
_WAKE_KEY_PREFIX = "hub:wake:"

# 最大静默硬上限 (分钟) — 不管 AI 设什么, 都不超过这个时间
MAX_SILENCE_MINUTES = 60


@dataclass
class WakeCondition:
    """单个唤醒条件"""
    type: str           # price_above / price_below / change_pct
    symbol: str = ""    # 交易对 (change_pct 可为空表示任意)
    value: float = 0.0  # 阈值


@dataclass
class WakeConfig:
    """一组唤醒条件配置"""
    conditions: List[dict]          # WakeCondition 列表
    timeout_minutes: int = 30       # 超时分钟数 (兜底)
    base_prices: dict = None        # 设定时的基准价格 (用于 change_pct)
    created_at: str = ""            # ISO 时间戳
    
    def __post_init__(self):
        if self.base_prices is None:
            self.base_prices = {}
        if not self.created_at:
            self.created_at = utc_now().isoformat()


class WakeMonitor:
    """唤醒条件监控器"""
    
    def _redis_key(self, user_id: int, agent_id: int) -> str:
        return f"{_WAKE_KEY_PREFIX}{user_id}:{agent_id}"
    
    async def _get_redis(self) -> aioredis.Redis:
        return aioredis.from_url(settings.redis_url, decode_responses=True)
    
    # ==================== 写入/读取/清除 ====================
    
    async def set_conditions(
        self,
        user_id: int,
        agent_id: int,
        conditions: List[dict],
        timeout_minutes: int = 30,
    ) -> dict:
        """
        设定唤醒条件 (由 AI 通过工具调用)
        
        Args:
            conditions: [{"type": "price_above", "symbol": "BTCUSDT", "value": 88000}, ...]
            timeout_minutes: 超时兜底 (被 MAX_SILENCE_MINUTES 限制)
        
        Returns:
            确认信息
        """
        # 超时硬上限
        timeout_minutes = min(timeout_minutes, MAX_SILENCE_MINUTES)
        timeout_minutes = max(timeout_minutes, 5)  # 最少 5 分钟
        
        # 获取当前基准价格 (用于 change_pct 计算)
        base_prices = await self._get_current_prices()
        
        config = WakeConfig(
            conditions=conditions,
            timeout_minutes=timeout_minutes,
            base_prices=base_prices,
        )
        
        r = await self._get_redis()
        try:
            key = self._redis_key(user_id, agent_id)
            ttl = timeout_minutes * 60 + 300  # 比超时多 5 分钟余量
            await r.set(key, json.dumps(asdict(config), ensure_ascii=False), ex=ttl)
            
            # 生成人类可读摘要
            summary_parts = []
            for c in conditions:
                ctype = c.get("type", "")
                sym = c.get("symbol", "")
                val = c.get("value", 0)
                if ctype == "price_above":
                    summary_parts.append(f"{sym} > {val}")
                elif ctype == "price_below":
                    summary_parts.append(f"{sym} < {val}")
                elif ctype == "change_pct":
                    target = sym or "任意币种"
                    summary_parts.append(f"{target} 变化 ≥ {val}%")
            
            summary = " 且 ".join(summary_parts) if summary_parts else "无条件"
            
            logger.info(
                f"[WakeMonitor] Conditions set for agent {user_id}:{agent_id}: "
                f"{summary}, timeout={timeout_minutes}min"
            )
            
            return {
                "success": True,
                "conditions_count": len(conditions),
                "timeout_minutes": timeout_minutes,
                "summary": summary,
                "message": f"唤醒条件已设定: {summary} (超时 {timeout_minutes} 分钟)",
            }
        finally:
            await r.aclose()
    
    async def get_conditions(self, user_id: int, agent_id: int) -> Optional[dict]:
        """读取当前唤醒条件 (供前端展示/daemon 检查)"""
        r = await self._get_redis()
        try:
            raw = await r.get(self._redis_key(user_id, agent_id))
            if raw:
                return json.loads(raw)
            return None
        finally:
            await r.aclose()
    
    async def clear_conditions(self, user_id: int, agent_id: int):
        """清除唤醒条件"""
        r = await self._get_redis()
        try:
            await r.delete(self._redis_key(user_id, agent_id))
        finally:
            await r.aclose()
    
    # ==================== 条件检查 ====================
    
    async def check_conditions(self, user_id: int, agent_id: int) -> Tuple[bool, str]:
        """
        检查唤醒条件是否全部满足 (AND 逻辑)
        
        Returns:
            (triggered: bool, reason: str)
            - triggered=True 时 reason 描述触发原因
            - triggered=False 时 reason 为空
        """
        config_raw = await self.get_conditions(user_id, agent_id)
        if not config_raw:
            return False, ""
        
        conditions = config_raw.get("conditions", [])
        base_prices = config_raw.get("base_prices", {})
        
        if not conditions:
            return False, ""
        
        # 检查超时
        created_at_str = config_raw.get("created_at", "")
        timeout_minutes = config_raw.get("timeout_minutes", 30)
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                elapsed = (utc_now() - created_at).total_seconds() / 60
                if elapsed >= timeout_minutes:
                    return True, f"超时唤醒 ({timeout_minutes}分钟)"
            except Exception:
                pass
        
        # 获取当前价格
        current_prices = await self._get_current_prices()
        if not current_prices:
            return False, ""
        
        # AND 逻辑: 检查每个条件是否满足
        all_met = True
        met_reasons = []
        
        for cond in conditions:
            ctype = cond.get("type", "")
            symbol = cond.get("symbol", "")
            value = float(cond.get("value", 0))
            
            if ctype == "price_above":
                price = current_prices.get(symbol, 0)
                if price > 0 and price >= value:
                    met_reasons.append(f"{symbol} {price:.1f} ≥ {value}")
                else:
                    all_met = False
                    break
            
            elif ctype == "price_below":
                price = current_prices.get(symbol, 0)
                if price > 0 and price <= value:
                    met_reasons.append(f"{symbol} {price:.1f} ≤ {value}")
                else:
                    all_met = False
                    break
            
            elif ctype == "change_pct":
                threshold = value
                # 检查指定币种或所有币种
                targets = [symbol] if symbol else list(base_prices.keys())
                target_met = False
                
                for sym in targets:
                    base = base_prices.get(sym, 0)
                    curr = current_prices.get(sym, 0)
                    if base > 0 and curr > 0:
                        change = abs(curr - base) / base * 100
                        if change >= threshold:
                            direction = "↑" if curr > base else "↓"
                            met_reasons.append(
                                f"{sym} {direction}{change:.1f}% (基准 {base:.1f})"
                            )
                            target_met = True
                            break
                
                if not target_met:
                    all_met = False
                    break
        
        if all_met and met_reasons:
            reason = " & ".join(met_reasons)
            return True, reason
        
        return False, ""
    
    async def wait_for_wake(
        self,
        user_id: int,
        agent_id: int,
        check_interval: int = 10,
        max_wait: int = None,
    ) -> Tuple[bool, str]:
        """
        阻塞等待唤醒条件满足
        
        Args:
            check_interval: 检查间隔 (秒)
            max_wait: 最大等待 (秒), None 使用条件中的 timeout
        
        Returns:
            (event_triggered: bool, reason: str)
            - event_triggered=True: 条件满足触发
            - event_triggered=False: 超时/无条件
        """
        config = await self.get_conditions(user_id, agent_id)
        if not config:
            return False, "无唤醒条件"
        
        timeout = config.get("timeout_minutes", 30)
        if max_wait is None:
            max_wait = timeout * 60
        max_wait = min(max_wait, MAX_SILENCE_MINUTES * 60)
        
        elapsed = 0
        while elapsed < max_wait:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            
            triggered, reason = await self.check_conditions(user_id, agent_id)
            if triggered:
                # 清除已触发的条件
                await self.clear_conditions(user_id, agent_id)
                logger.info(
                    f"[WakeMonitor] TRIGGERED for {user_id}:{agent_id}: {reason}"
                )
                return True, reason
        
        # 超时
        await self.clear_conditions(user_id, agent_id)
        return False, f"等待超时 ({max_wait // 60}min)"
    
    # ==================== 辅助 ====================
    
    async def _get_current_prices(self) -> dict:
        """从 Redis 获取 MarketCollector 推送的实时价格"""
        prices = {}
        r = await self._get_redis()
        try:
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
            for sym in symbols:
                data = await r.hgetall(f"autotrade:market:{sym}")
                if data and data.get("price"):
                    try:
                        prices[sym] = float(data["price"])
                    except (ValueError, TypeError):
                        pass
        finally:
            await r.aclose()
        return prices
    
    def format_conditions_display(self, config: dict) -> str:
        """格式化条件为前端展示文本"""
        conditions = config.get("conditions", [])
        timeout = config.get("timeout_minutes", 30)
        created_at = config.get("created_at", "")
        
        if not conditions:
            return "无唤醒条件"
        
        parts = []
        for c in conditions:
            ctype = c.get("type", "")
            sym = c.get("symbol", "")
            val = c.get("value", 0)
            if ctype == "price_above":
                parts.append(f"{sym} > {val}")
            elif ctype == "price_below":
                parts.append(f"{sym} < {val}")
            elif ctype == "change_pct":
                target = sym or "任意币种"
                parts.append(f"{target} 变化 ≥ {val}%")
        
        conditions_text = " 且 ".join(parts)
        
        # 计算剩余等待时间
        remaining = ""
        if created_at:
            try:
                created = datetime.fromisoformat(created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                elapsed_min = (utc_now() - created).total_seconds() / 60
                remaining_min = max(0, timeout - elapsed_min)
                remaining = f"，剩余 {int(remaining_min)} 分钟"
            except Exception:
                pass
        
        return f"等待: {conditions_text} (超时 {timeout}min{remaining})"


# 全局单例
wake_monitor = WakeMonitor()
