import subprocess
import re

cmd = [
    'ssh', '-T', '-o', 'ConnectTimeout=15', 'root@45.77.26.211',
    "docker logs --since '2026-04-01T00:00:00' autotrade-backend 2>&1"
]

r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

lines = r.stdout.split('\n')
print(f"Total log lines today: {len(lines)}")

# Filter for hub/agent/trade related
keywords = ['hub_daemon', 'HubDaemon', 'hub_agent', 'HubAgent', 'open_position', 
            'place_order', 'execute_trade', 'tool_call', 'tool_result', 
            'wake', 'cycle', 'ERROR', 'error', 'analyze', 'daemon']
pattern = re.compile('|'.join(keywords), re.IGNORECASE)

filtered = [l for l in lines if pattern.search(l) and 'HTTP/1.1' not in l]
print(f"Filtered hub/agent lines: {len(filtered)}")
print("=" * 80)
for l in filtered[-100:]:
    print(l)

# Also look for any trade/order activity
trade_kw = re.compile(r'open_position|place_order|execute|order|trade|signal', re.IGNORECASE)
trade_lines = [l for l in lines if trade_kw.search(l) and 'HTTP/1.1' not in l]
print("\n" + "=" * 80)
print(f"Trade-related lines: {len(trade_lines)}")
for l in trade_lines[-50:]:
    print(l)

with open(r'd:\AutoTrade\_hub_analysis.txt', 'w', encoding='utf-8') as f:
    f.write(f"Total log lines today: {len(lines)}\n")
    f.write(f"Hub/agent lines: {len(filtered)}\n")
    f.write(f"Trade lines: {len(trade_lines)}\n\n")
    f.write("=== HUB/AGENT LOGS ===\n")
    for l in filtered[-100:]:
        f.write(l + '\n')
    f.write("\n=== TRADE LOGS ===\n")
    for l in trade_lines[-50:]:
        f.write(l + '\n')

print("\nSaved to _hub_analysis.txt")
