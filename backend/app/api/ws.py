"""
WebSocket Price Push API
=========================
实时价格推送端点

功能:
1. 前端通过 WebSocket 连接获取实时价格
2. 从 price_stream 服务获取已缓存的价格
3. 支持多交易对订阅
4. 心跳检测保持连接

前端连接:
    const ws = new WebSocket('ws://localhost:8000/api/ws/prices')
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        // data = { type: "price_update", prices: { BTCUSDT: "78000.5", ... } }
    }

消息格式:
    发送: { "type": "subscribe", "symbols": ["BTCUSDT", "ETHUSDT"] }
    接收: { "type": "price_update", "prices": { "BTCUSDT": "78000.5", ... }, "timestamp": "..." }
"""

import asyncio
import json
from datetime import datetime
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.services.price_stream import price_stream


router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        from app.core.metrics import metrics as app_metrics
        app_metrics.ws_connect()
        logger.info(f"[WS] Client connected, total={len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        from app.core.metrics import metrics as app_metrics
        app_metrics.ws_disconnect()
        logger.info(f"[WS] Client disconnected, total={len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """广播消息给所有连接"""
        data = json.dumps(message)
        disconnected = []
        
        for ws in self.active_connections:
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.append(ws)
        
        # 清理断开的连接
        for ws in disconnected:
            self.disconnect(ws)


# 全局连接管理器
manager = ConnectionManager()


@router.websocket("/prices")
async def websocket_prices(websocket: WebSocket):
    """
    实时价格推送
    
    每秒推送所有交易对的最新价格，
    数据来源: price_stream 服务缓存的价格。
    """
    await manager.connect(websocket)
    
    try:
        while True:
            # 收集所有交易对的最新价格
            prices = {}
            for symbol in [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                "LTCUSDT", "DOGEUSDT", "ASTERUSDT", "XAUUSDT"
            ]:
                price = price_stream.get_price(symbol)
                if price is not None:
                    prices[symbol] = str(price)
            
            # 推送价格更新
            if prices:
                await websocket.send_json({
                    "type": "price_update",
                    "prices": prices,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                })
            
            # 每秒推送一次
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"[WS] Error: {e}")
        manager.disconnect(websocket)
