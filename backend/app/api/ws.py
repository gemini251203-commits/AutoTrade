"""
WebSocket Price Push API
=========================
鐎圭偞妞傛禒閿嬬壐閹恒劑鈧胶顏悙?

閸旂喕鍏?
1. 閸撳秶顏柅姘崇箖 WebSocket 鏉╃偞甯撮懢宄板絿鐎圭偞妞傛禒閿嬬壐
2. 娴?price_stream 閺堝秴濮熼懢宄板絿瀹歌尙绱︾€涙娈戞禒閿嬬壐
3. 閺€顖涘瘮婢舵矮姘﹂弰鎾愁嚠鐠併垽妲?
4. 韫囧啳鐑﹀Λ鈧ù瀣╃箽閹镐浇绻涢幒?

閸撳秶顏潻鐐村复:
    const ws = new WebSocket('ws://localhost:8000/api/ws/prices')
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        // data = { type: "price_update", prices: { BTCUSDT: "78000.5", ... } }
    }

濞戝牊浼呴弽鐓庣础:
    閸欐垿鈧? { "type": "subscribe", "symbols": ["BTCUSDT", "ETHUSDT"] }
    閹恒儲鏁? { "type": "price_update", "prices": { "BTCUSDT": "78000.5", ... }, "timestamp": "..." }
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
    """WebSocket 鏉╃偞甯寸粻锛勬倞閸?""
    
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
        """楠炴寧鎸卞☉鍫熶紖缂佹瑦澧嶉張澶庣箾閹?""
        data = json.dumps(message)
        disconnected = []
        
        for ws in self.active_connections:
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.append(ws)
        
        # 濞撳懐鎮婇弬顓炵磻閻ㄥ嫯绻涢幒?
        for ws in disconnected:
            self.disconnect(ws)


# 閸忋劌鐪潻鐐村复缁狅紕鎮婇崳?
manager = ConnectionManager()


@router.websocket("/prices")
async def websocket_prices(websocket: WebSocket):
    """
    鐎圭偞妞傛禒閿嬬壐閹恒劑鈧?
    
    濮ｅ繒顫楅幒銊┾偓浣瑰閺堝姘﹂弰鎾愁嚠閻ㄥ嫭娓堕弬棰佺幆閺嶇》绱?
    閺佺増宓侀弶銉︾爱: price_stream 閺堝秴濮熺紓鎾崇摠閻ㄥ嫪鐜弽绗衡偓?
    """
    await manager.connect(websocket)
    
    try:
        while True:
            # 閺€鍫曟肠閹碘偓閺堝姘﹂弰鎾愁嚠閻ㄥ嫭娓堕弬棰佺幆閺?
            prices = {}
            for symbol in [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                "LTCUSDT", "DOGEUSDT", "ASTERUSDT", "XAUUSDT"
            ]:
                price = price_stream.get_price(symbol)
                if price is not None:
                    prices[symbol] = str(price)
            
            # 閹恒劑鈧椒鐜弽鍏兼纯閺?
            if prices:
                await websocket.send_json({
                    "type": "price_update",
                    "prices": prices,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                })
            
            # 濮ｅ繒顫楅幒銊┾偓浣风濞?
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"[WS] Error: {e}")
        manager.disconnect(websocket)
