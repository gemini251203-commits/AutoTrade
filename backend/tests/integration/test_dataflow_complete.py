"""
全链路数据流验证测试
======================
验证前端 -> 后端 -> 数据库的完整数据流

测试内容:
1. 认证 (Auth)
2. 钱包余额 (Wallet)
3. 开仓 (Position Open) - 验证字段映射
4. 仓位列表 (Position List)
5. 风险查询 (Risk Positions)
6. 平仓 (Position Close)
"""
import httpx
import asyncio
from decimal import Decimal

BASE_URL = "http://localhost:8000"

async def run_test():
    async with httpx.AsyncClient(timeout=30) as client:
        print("=" * 60)
        print("全链路数据流验证测试")
        print("=" * 60)
        
        # 1. 认证
        print("\n[1] 认证测试...")
        login_data = {"username": "admin", "password": "admin"}
        r = await client.post(f"{BASE_URL}/api/auth/token", data=login_data)
        assert r.status_code == 200, f"认证失败: {r.text}"
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"   ✅ 认证成功, Token: {token[:20]}...")
        
        # 2. 钱包余额
        print("\n[2] 钱包余额测试...")
        r = await client.get(f"{BASE_URL}/api/wallet/balance", headers=headers)
        assert r.status_code == 200, f"钱包查询失败: {r.text}"
        wallet = r.json()
        print(f"   ✅ 余额: available={wallet['available']}, frozen={wallet['frozen']}")
        
        # 记录初始余额
        initial_available = Decimal(wallet['available'])
        
        # 3. 开仓测试 - 验证字段映射
        print("\n[3] 开仓测试 (验证字段映射)...")
        # 用正确的后端字段名
        open_payload = {
            "symbol": "BTCUSDT",
            "side": "long",        # 后端期望 'long'/'short', 不是 'buy'/'sell'
            "quantity": "0.01",    # Decimal string
            "entry_price": "80000", # 后端字段名是 entry_price, 不是 price
            "leverage": 10,
            "margin_mode": "isolated",  # 'cross' 或 'isolated'
            "stop_loss": "75000",
            "take_profit": "90000",
        }
        print(f"   发送的 payload: {open_payload}")
        
        r = await client.post(f"{BASE_URL}/api/position/open", json=open_payload, headers=headers)
        if r.status_code != 200:
            print(f"   ❌ 开仓失败: {r.status_code} - {r.text}")
            return
        
        position = r.json()
        print(f"   ✅ 开仓成功!")
        print(f"   返回字段:")
        print(f"      id={position['id']}")
        print(f"      symbol={position['symbol']}")
        print(f"      side={position['side']}")
        print(f"      size={position['size']}")
        print(f"      entry_price={position['entry_price']}")
        print(f"      leverage={position['leverage']}")
        print(f"      margin={position['margin']}")
        print(f"      margin_mode={position['margin_mode']}")
        print(f"      stop_loss={position['stop_loss']}")
        print(f"      take_profit={position['take_profit']}")
        print(f"      liquidation_price={position.get('liquidation_price')}")
        
        position_id = position['id']
        
        # 4. 钱包余额变化验证
        print("\n[4] 验证保证金冻结...")
        r = await client.get(f"{BASE_URL}/api/wallet/balance", headers=headers)
        wallet_after = r.json()
        new_available = Decimal(wallet_after['available'])
        frozen = Decimal(wallet_after['frozen'])
        
        margin = Decimal(position['margin'])
        expected_available = initial_available - margin
        
        print(f"   初始余额: {initial_available}")
        print(f"   开仓保证金: {margin}")
        print(f"   期望剩余: {expected_available}")
        print(f"   实际剩余: {new_available}")
        print(f"   冻结金额: {frozen}")
        
        if abs(new_available - expected_available) < Decimal("0.01"):
            print(f"   ✅ 保证金冻结正确!")
        else:
            print(f"   ⚠️ 保证金计算可能有偏差")
        
        # 5. 风险查询 - 验证 PositionRisk 接口
        print("\n[5] 风险查询测试 (验证 PositionRisk 接口)...")
        r = await client.get(f"{BASE_URL}/api/risk/positions", headers=headers)
        assert r.status_code == 200, f"风险查询失败: {r.text}"
        risks = r.json()
        
        if risks:
            risk = risks[0]
            print(f"   ✅ 返回字段 (前端 PositionRisk interface):")
            print(f"      position_id={risk['position_id']}")
            print(f"      symbol={risk['symbol']}")
            print(f"      side={risk['side']}")
            print(f"      size={risk['size']}")
            print(f"      entry_price={risk['entry_price']}")
            print(f"      mark_price={risk['mark_price']}")
            print(f"      leverage={risk['leverage']}")
            print(f"      margin={risk['margin']}")
            print(f"      liquidation_price={risk.get('liquidation_price')}")
            print(f"      unrealized_pnl={risk['unrealized_pnl']}")
            print(f"      roe_percent={risk['roe_percent']}")
            print(f"      margin_ratio={risk['margin_ratio']}")
            print(f"      is_at_risk={risk['is_at_risk']}")
            print(f"      should_liquidate={risk['should_liquidate']}")
        else:
            print(f"   ⚠️ 没有返回风险数据")
        
        # 6. 平仓测试 - 验证字段映射
        print("\n[6] 平仓测试 (验证 ClosePositionRequest)...")
        close_payload = {
            "close_price": "81000",  # 后端期望 close_price
            "quantity": "0.01",       # 可选，不填则全平
        }
        print(f"   发送的 payload: {close_payload}")
        
        r = await client.post(f"{BASE_URL}/api/position/{position_id}/close", json=close_payload, headers=headers)
        if r.status_code != 200:
            print(f"   ❌ 平仓失败: {r.status_code} - {r.text}")
            return
        
        close_result = r.json()
        print(f"   ✅ 平仓成功!")
        print(f"   已实现盈亏: {close_result['realized_pnl']}")
        
        # 7. 最终余额验证
        print("\n[7] 最终余额验证...")
        r = await client.get(f"{BASE_URL}/api/wallet/balance", headers=headers)
        final_wallet = r.json()
        final_available = Decimal(final_wallet['available'])
        final_frozen = Decimal(final_wallet['frozen'])
        
        print(f"   初始余额: {initial_available}")
        print(f"   最终余额: {final_available}")
        print(f"   最终冻结: {final_frozen}")
        print(f"   盈亏: {close_result['realized_pnl']}")
        
        # 验证: 最终余额 ≈ 初始余额 + 盈亏
        expected_final = initial_available + Decimal(str(close_result['realized_pnl']))
        if abs(final_available - expected_final) < Decimal("0.01"):
            print(f"   ✅ 余额结算正确!")
        else:
            print(f"   ⚠️ 余额结算有偏差")
            print(f"   期望: {expected_final}")
            print(f"   实际: {final_available}")
        
        print("\n" + "=" * 60)
        print("✅ 全链路数据流验证完成!")
        print("=" * 60)
        
        # 输出字段映射总结
        print("\n📋 字段映射总结:")
        print("-" * 40)
        print("TradePanel.vue -> POST /position/open:")
        print("  side: 'long'/'short' (非 'buy'/'sell')")
        print("  entry_price: 开仓价 (非 'price')")
        print("  margin_mode: 'cross'/'isolated'")
        print("  quantity: Decimal string")
        print("-" * 40)
        print("PositionList.vue -> POST /position/{id}/close:")
        print("  close_price: 平仓价 (必填)")
        print("  quantity: 平仓数量 (可选)")
        print("-" * 40)
        print("PositionList.vue <- GET /risk/positions:")
        print("  对应 PositionRisk interface 所有字段")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
