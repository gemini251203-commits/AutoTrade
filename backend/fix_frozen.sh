#!/bin/bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Lin0510!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Token: ${TOKEN:0:20}..."

curl -s -X POST http://localhost:8000/api/wallet/fix-frozen \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool
