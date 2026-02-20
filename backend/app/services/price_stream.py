"""
Price Stream Service
=====================
使用 Binance WebSocket 实时价格流进行订单撮合

功能:
1. 订阅多个交易对的实时价格
2. 价格更新时立即检查限价单和条件单
3. 毫秒级订单撮合响应

启动方式:
- 应用启动时自动启动 (在 main.py 的 lifespan 中)
"""

import asyncio
from decimal import Decimal
from typing import Dict, Optional, Set
import json

import websockets
from loguru import logger

from app.db.session import AsyncSessionLocal
from app.services.trading import OrderExecutor


class PriceStreamService:
    """
    实时价格流服务
    
    使用 Binance WebSocket 获取实时价格，
    实现毫秒级订单撮合 + 止损止盈 + 强平监控。
    """
    
    # Binance WebSocket 端点
    BINANCE_WS_URL = "wss://fstream.binance.com/ws"
    
    # 订阅的交易对 (小写) - 9个交易对
    SYMBOLS = [
        "btcusdt", "ethusdt", "bnbusdt", "solusdt", "xrpusdt",
        "ltcusdt", "dogeusdt", "asterusdt", "xauusdt"
    ]
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._prices: Dict[str, Decimal] = {}
        self._ws = None
        
        # 防抖: 每个交易对最多每秒检查一次
        self._last_check: Dict[str, float] = {}
        self._check_interval = 1.0  # 秒
    
    async def start(self):
        """启动价格流服务"""
        if self._running:
            logger.warning("[PriceStream] Already running")
            return
        
        self._running = True
        logger.info("[PriceStream] Starting WebSocket price stream...")
        
        self._task = asyncio.create_task(self._run_loop())
    
    async def stop(self):
        """停止服务"""
        self._running = False
        
        if self._ws:
            await self._ws.close()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("[PriceStream] Stopped")
    
    async def _run_loop(self):
        """主循环 - 连接 WebSocket 并处理消息"""
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error(f"[PriceStream] Connection error: {e}")
                await asyncio.sleep(5)  # 重连延迟
    
    async def _connect_and_listen(self):
        """连接 WebSocket 并监听价格更新"""
        # 构建订阅流名称: btcusdt@aggTrade
        streams = [f"{s}@aggTrade" for s in self.SYMBOLS]
        stream_path = "/".join(streams)
        url = f"{self.BINANCE_WS_URL}/{stream_path}"
        
        logger.info(f"[PriceStream] Connecting to Binance WebSocket...")
        
        async with websockets.connect(url) as ws:
            self._ws = ws
            logger.info(f"[PriceStream] Connected! Subscribed to {len(self.SYMBOLS)} symbols")
            
            async for message in ws:
                if not self._running:
                    break
                
                try:
                    await self._handle_message(message)
                except Exception as e:
                    logger.warning(f"[PriceStream] Message handling error: {e}")
    
    async def _handle_message(self, raw_message: str):
        """处理 WebSocket 消息"""
        data = json.loads(raw_message)
        
        # aggTrade 格式: {"e": "aggTrade", "s": "BTCUSDT", "p": "77000.50", ...}
        event_type = data.get("e")
        if event_type != "aggTrade":
            return
        
        symbol = data.get("s", "").upper()  # BTCUSDT
        price_str = data.get("p", "0")
        
        try:
            price = Decimal(price_str)
        except:
            return
        
        # 更新缓存价格
        self._prices[symbol] = price
        
        # 防抖检查
        import time
        now = time.time()
        last = self._last_check.get(symbol, 0)
        
        if now - last >= self._check_interval:
            self._last_check[symbol] = now
            
            # 异步检查订单
            asyncio.create_task(self._check_orders(symbol, price))
    
    async def _check_orders(self, symbol: str, current_price: Decimal):
        """检查该交易对的挂单 + 仓位止损止盈 + 强平"""
        try:
            async with AsyncSessionLocal() as db:
                # 检查限价单
                filled = await OrderExecutor.check_limit_orders(
                    db, symbol, current_price
                )
                
                # 🔥 网格回调: 限价单成交后触发网格策略
                if filled:
                    from app.services.grid import GridStrategy
                    for order in filled:
                        try:
                            await GridStrategy.on_order_filled(db, order)
                        except Exception as ge:
                            logger.warning(f"[PriceStream] Grid callback error: {ge}")
                
                # 检查条件单
                triggered = await OrderExecutor.check_conditional_orders(
                    db, symbol, current_price
                )
                
                # 🔥 检查仓位止损/止盈
                sl_tp_closed = await OrderExecutor.check_position_sl_tp(
                    db, symbol, current_price
                )
                
                # 🔥 检查强平 (替代原来缺失的定时任务)
                from app.services.risk import RiskEngine
                price_map = {symbol: current_price}
                liquidated = await RiskEngine.monitor_positions(db, price_map)
                
                has_changes = filled or triggered or sl_tp_closed or liquidated
                if has_changes:
                    await db.commit()
                    
                    if filled:
                        logger.info(
                            f"[PriceStream] {len(filled)} limit orders filled "
                            f"for {symbol} @ {current_price}"
                        )
                    if triggered:
                        logger.info(
                            f"[PriceStream] {len(triggered)} conditional orders triggered "
                            f"for {symbol} @ {current_price}"
                        )
                    if sl_tp_closed:
                        logger.warning(
                            f"[PriceStream] ⚠️ {len(sl_tp_closed)} positions SL/TP closed "
                            f"for {symbol} @ {current_price}"
                        )
                    if liquidated:
                        logger.warning(
                            f"[PriceStream] 🔥 {len(liquidated)} positions LIQUIDATED "
                            f"for {symbol} @ {current_price}"
                        )
                        
        except Exception as e:
            logger.error(f"[PriceStream] Order check error: {e}")
    
    def get_price(self, symbol: str) -> Optional[Decimal]:
        """获取缓存的最新价格"""
        return self._prices.get(symbol.upper())


# 全局单例
price_stream = PriceStreamService()
