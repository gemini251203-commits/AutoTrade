#!/bin/bash
# ==== Autopilot API Black-box Test ====
set -e

BASE="http://localhost:8000"
echo "===== Autopilot API Test ====="
echo ""

# 1. Login
echo "--- 1. Login ---"
LOGIN_RESP=$(curl -s -X POST "$BASE/api/auth/token" \
  -d "username=admin&password=admin" \
  -H "Content-Type: application/x-www-form-urlencoded")
TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token obtained: ${TOKEN:0:20}..."
echo ""

AUTH="Authorization: Bearer $TOKEN"

# 2. Get Status (before start)
echo "--- 2. Status (before start) ---"
curl -s "$BASE/api/agent/autopilot/status" -H "$AUTH" | python3 -m json.tool
echo ""

# 3. Get Logs (before start)
echo "--- 3. Logs (before start, limit=3) ---"
curl -s "$BASE/api/agent/autopilot/logs?limit=3" -H "$AUTH" | python3 -m json.tool
echo ""

# 4. Start Autopilot
echo "--- 4. Start Autopilot ---"
curl -s -X POST "$BASE/api/agent/autopilot/start" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d '{"symbols":["BTCUSDT"],"interval":"15m","intervals":["5m","1h","4h"]}' | python3 -m json.tool
echo ""

# 5. Status after start
echo "--- 5. Status (after start) ---"
sleep 2
curl -s "$BASE/api/agent/autopilot/status" -H "$AUTH" | python3 -m json.tool
echo ""

# 6. Run Once manually
echo "--- 6. Run Once (BTCUSDT) ---"
curl -s -X POST "$BASE/api/agent/autopilot/run-once?symbol=BTCUSDT" -H "$AUTH" | python3 -m json.tool
echo ""

# 7. Wait and get logs
echo "--- 7. Logs (after run-once, limit=5) ---"
sleep 5
curl -s "$BASE/api/agent/autopilot/logs?limit=5" -H "$AUTH" | python3 -m json.tool
echo ""

# 8. Stop Autopilot
echo "--- 8. Stop Autopilot ---"
curl -s -X POST "$BASE/api/agent/autopilot/stop" -H "$AUTH" | python3 -m json.tool
echo ""

# 9. Status after stop
echo "--- 9. Status (after stop) ---"
curl -s "$BASE/api/agent/autopilot/status" -H "$AUTH" | python3 -m json.tool
echo ""

# 10. Clear logs
echo "--- 10. Clear Logs ---"
curl -s -X DELETE "$BASE/api/agent/autopilot/logs" -H "$AUTH" | python3 -m json.tool
echo ""

echo "===== Test Complete ====="
