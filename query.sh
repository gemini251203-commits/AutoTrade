#!/bin/bash
docker exec -i db psql -U postgres -d autotrade -x -c "SELECT id, symbol, side, source, open_reason, created_at FROM trade_memories ORDER BY id DESC LIMIT 10;"
docker exec -i db psql -U postgres -d autotrade -x -c "SELECT id, user_id, symbol, is_active FROM strategies WHERE is_active=true;"
