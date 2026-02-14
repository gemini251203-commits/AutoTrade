"""
AutoTrade Connection Test Script
=================================
测试网络连通性和 AI 服务可用性

运行: python test_connection.py
"""

import os
import sys
import asyncio
from pathlib import Path

# 加载 .env 文件
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[OK] Loaded .env from: {env_path}")

import httpx


class SimpleNetworkManager:
    """简化版网络管理器 (仅用于测试)"""
    
    def __init__(self):
        self._use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        self._proxy_url = os.getenv("PROXY_URL", "")
        
        if self._use_proxy and self._proxy_url:
            self._proxy = self._proxy_url
            print(f"[OK] Proxy Mode: {self._proxy_url}")
        else:
            self._proxy = None
            print("[OK] Direct Mode (No Proxy)")
    
    @property
    def use_proxy(self) -> bool:
        return self._use_proxy
    
    @property
    def proxy_url(self) -> str:
        return self._proxy_url
    
    def get_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            proxy=self._proxy,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )


net_manager = SimpleNetworkManager()


async def test_proxy_connectivity() -> bool:
    """Test 1: Proxy/Network connectivity via Google"""
    print("\n" + "=" * 50)
    print("Test 1: Proxy/Network Connectivity (Google)")
    print("=" * 50)
    
    try:
        async with net_manager.get_client(timeout=10.0) as client:
            response = await client.get("https://www.google.com")
            
            if response.status_code == 200:
                print(f"[PASS] Google connected! (Status: {response.status_code})")
                return True
            else:
                print(f"[WARN] Google response abnormal (Status: {response.status_code})")
                return False
                
    except Exception as e:
        print(f"[FAIL] Google connection failed!")
        print(f"       Error: {type(e).__name__}: {e}")
        return False


async def test_deepseek_connectivity() -> bool:
    """Test 2: DeepSeek AI connectivity"""
    print("\n" + "=" * 50)
    print("Test 2: DeepSeek AI Connectivity")
    print("=" * 50)
    
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    
    if not api_key or api_key == "your_deepseek_api_key_here":
        print("[SKIP] DEEPSEEK_API_KEY not configured")
        return False
    
    print(f"       API Key: {api_key[:8]}...{api_key[-4:]}")
    
    try:
        async with net_manager.get_client(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "user", "content": "Say OK only."}
                    ],
                    "max_tokens": 5,
                },
            )
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                print(f"[PASS] DeepSeek AI connected!")
                print(f"       AI Response: {content.strip()}")
                return True
            elif response.status_code == 401:
                print(f"[FAIL] API Key invalid (401 Unauthorized)")
                return False
            elif response.status_code == 402:
                print(f"[WARN] Insufficient balance (402)")
                return False
            else:
                print(f"[FAIL] API request failed (Status: {response.status_code})")
                return False
                
    except Exception as e:
        print(f"[FAIL] DeepSeek connection failed!")
        print(f"       Error: {type(e).__name__}: {e}")
        return False


async def main():
    """Main test function"""
    print("\n" + "=" * 50)
    print("AutoTrade Connection Test")
    print("=" * 50)
    
    proxy_ok = await test_proxy_connectivity()
    ai_ok = await test_deepseek_connectivity()
    
    print("\n" + "=" * 50)
    print("Test Results Summary")
    print("=" * 50)
    print(f"  Proxy/Network: {'PASS' if proxy_ok else 'FAIL'}")
    print(f"  DeepSeek AI:   {'PASS' if ai_ok else 'FAIL'}")
    print("=" * 50 + "\n")
    
    return proxy_ok and ai_ok


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[WARN] Test interrupted by user")
        sys.exit(1)
