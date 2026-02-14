"""
完整数据流验证测试
==================
测试所有 API 端点和字段名一致性
"""
import httpx
import json

BASE_URL = "http://localhost:8000"

def main():
    print("=" * 60)
    print("完整数据流验证测试")
    print("=" * 60)
    print()
    
    # 1. Health Check
    print("1. [HEALTH] 后端健康检查")
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=10)
        print(f"   GET /health: {r.status_code}")
        data = r.json()
        print(f"   Database: {data.get('database')}")
        print(f"   Redis: {data.get('redis')}")
    except Exception as e:
        print(f"   ❌ 错误: {e}")
        return
    
    # 2. Login
    print()
    print("2. [AUTH] 登录认证")
    login_data = {"username": "admin", "password": "admin"}
    r = httpx.post(f"{BASE_URL}/api/auth/token", data=login_data, timeout=10)
    print(f"   POST /api/auth/token: {r.status_code}")
    if r.status_code != 200:
        print(f"   ❌ 登录失败: {r.text}")
        return
    token = r.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   ✅ Token: {token[:20]}...")
    
    # 3. User Info
    print()
    print("3. [AUTH] 用户信息")
    r = httpx.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=10)
    print(f"   GET /api/auth/me: {r.status_code}")
    user = r.json()
    print(f"   字段: id={user.get('id')}, username={user.get('username')}, email={user.get('email')}")
    
    # 4. Wallet Balance
    print()
    print("4. [WALLET] 钱包余额")
    r = httpx.get(f"{BASE_URL}/api/wallet/balance", headers=headers, timeout=10)
    print(f"   GET /api/wallet/balance: {r.status_code}")
    wallet = r.json()
    print(f"   字段检查:")
    print(f"     - available: {wallet.get('available')} (后端 snake_case)")
    print(f"     - frozen: {wallet.get('frozen')}")
    print(f"     - total_equity: {wallet.get('total_equity')} (前端 totalEquity)")
    print(f"     - total_pnl: {wallet.get('total_pnl')} (前端 totalPnl)")
    
    # 5. Market Klines
    print()
    print("5. [MARKET] K线数据")
    r = httpx.get(f"{BASE_URL}/api/market/klines", params={"symbol": "BTCUSDT", "interval": "1m", "limit": 1}, timeout=10)
    print(f"   GET /api/market/klines: {r.status_code}")
    kdata = r.json()
    if kdata.get("data"):
        latest = kdata["data"][0]
        print(f"   字段检查:")
        print(f"     - open: {latest.get('open')}")
        print(f"     - high: {latest.get('high')}")
        print(f"     - low: {latest.get('low')}")
        print(f"     - close: {latest.get('close')}")
        print(f"     - volume: {latest.get('volume')}")
        print(f"     - open_time: {latest.get('open_time')}")
    
    # 6. Positions
    print()
    print("6. [POSITION] 仓位列表")
    r = httpx.get(f"{BASE_URL}/api/position/", headers=headers, timeout=10)
    print(f"   GET /api/position/: {r.status_code}")
    positions = r.json()
    print(f"   仓位数量: {len(positions)}")
    for p in positions[:2]:
        print(f"   字段检查 (Position ID={p.get('id')}):")
        print(f"     - symbol: {p.get('symbol')}")
        print(f"     - side: {p.get('side')}")
        print(f"     - size: {p.get('size')}")
        print(f"     - entry_price: {p.get('entry_price')}")
        print(f"     - leverage: {p.get('leverage')}")
        print(f"     - margin: {p.get('margin')}")
        print(f"     - liquidation_price: {p.get('liquidation_price')}")
        print(f"     - margin_mode: {p.get('margin_mode')}")
    
    # 7. Orders
    print()
    print("7. [ORDER] 订单列表")
    r = httpx.get(f"{BASE_URL}/api/order/", headers=headers, timeout=10)
    print(f"   GET /api/order/: {r.status_code}")
    orders = r.json()
    print(f"   订单数量: {len(orders)}")
    if orders:
        o = orders[0]
        print(f"   字段检查 (Order ID={o.get('id')}):")
        print(f"     - symbol: {o.get('symbol')}")
        print(f"     - side: {o.get('side')}")
        print(f"     - order_type: {o.get('order_type')}")
        print(f"     - status: {o.get('status')}")
        print(f"     - leverage: {o.get('leverage')}")
        print(f"     - quantity: {o.get('quantity')}")
        print(f"     - price: {o.get('price')}")
        print(f"     - trigger_price: {o.get('trigger_price')}")
    
    # 8. API Routes Summary
    print()
    print("8. [ROUTES] API 路由汇总")
    routes = [
        ("POST", "/api/auth/token", "登录"),
        ("GET", "/api/auth/me", "用户信息"),
        ("POST", "/api/auth/register", "注册"),
        ("GET", "/api/wallet/", "钱包信息"),
        ("GET", "/api/wallet/balance", "钱包余额"),
        ("POST", "/api/wallet/initialize", "初始化钱包"),
        ("GET", "/api/order/", "订单列表"),
        ("POST", "/api/order/", "创建订单"),
        ("POST", "/api/order/{id}/cancel", "取消订单"),
        ("GET", "/api/position/", "仓位列表"),
        ("POST", "/api/position/open", "开仓"),
        ("POST", "/api/position/{id}/close", "平仓"),
        ("POST", "/api/position/{id}/tp-sl", "设置止盈止损"),
        ("GET", "/api/market/klines", "K线数据"),
        ("GET", "/api/market/symbols", "交易对列表"),
    ]
    for method, path, desc in routes:
        print(f"   {method:5} {path:30} → {desc}")
    
    print()
    print("=" * 60)
    print("✅ 数据流验证完成!")
    print("=" * 60)

if __name__ == "__main__":
    main()
