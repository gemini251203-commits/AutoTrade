import subprocess
import re

# Get ALL recent logs (last 1000 lines) without time filter
cmd = [
    'ssh', '-T', '-o', 'ConnectTimeout=15', 'root@45.77.26.211',
    "docker logs --tail 1000 autotrade-backend 2>&1"
]

r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

lines = r.stdout.split('\n')
print(f"Total log lines (tail 1000): {len(lines)}")

# Show the first few and last few lines to see time range
print("\n=== FIRST 5 LINES ===")
for l in lines[:5]:
    print(l)
print("\n=== LAST 5 LINES ===")
for l in lines[-6:]:
    print(l)

# Filter for hub/agent/trade related (exclude HTTP access logs)
keywords_hub = ['hub_daemon', 'HubDaemon', 'hub_agent', 'HubAgent', 
                'daemon', 'cycle', 'wake', 'autopilot']
pattern_hub = re.compile('|'.join(keywords_hub), re.IGNORECASE)
hub_lines = [l for l in lines if pattern_hub.search(l) and '\"GET ' not in l and '\"POST ' not in l and '\"PUT ' not in l]

print(f"\n=== HUB/DAEMON LINES ({len(hub_lines)}) ===")
for l in hub_lines[-60:]:
    print(l)

# Filter for tool calls and AI responses
tool_kw = re.compile(r'tool_call|tool_result|function_call|open_position|place_order|execute|DeepSeek|GPT|Claude|openai|LLM|token|completion', re.IGNORECASE)
tool_lines = [l for l in lines if tool_kw.search(l) and '\"GET ' not in l and '\"POST ' not in l]

print(f"\n=== TOOL/AI LINES ({len(tool_lines)}) ===")
for l in tool_lines[-40:]:
    print(l)

# Filter for errors
error_kw = re.compile(r'ERROR|Exception|Traceback|Failed|error', re.IGNORECASE)
error_lines = [l for l in lines if error_kw.search(l) and '\"GET ' not in l and '\"POST ' not in l]

print(f"\n=== ERROR LINES ({len(error_lines)}) ===")
for l in error_lines[-40:]:
    print(l)

# Save all to file
with open(r'd:\AutoTrade\_hub_analysis2.txt', 'w', encoding='utf-8') as f:
    f.write(f"Total lines: {len(lines)}\n")
    f.write(f"Hub lines: {len(hub_lines)}\n")
    f.write(f"Tool/AI lines: {len(tool_lines)}\n")
    f.write(f"Error lines: {len(error_lines)}\n\n")
    
    f.write("=== ALL HUB LINES ===\n")
    for l in hub_lines:
        f.write(l + '\n')
    
    f.write("\n=== ALL TOOL/AI LINES ===\n")
    for l in tool_lines:
        f.write(l + '\n')
    
    f.write("\n=== ALL ERROR LINES ===\n")
    for l in error_lines:
        f.write(l + '\n')
    
    f.write("\n=== FULL NON-HTTP LOGS ===\n")
    for l in lines:
        if l.strip() and '\"GET ' not in l and '\"POST ' not in l and '\"PUT ' not in l and '\"DELETE ' not in l:
            f.write(l + '\n')

print("\nSaved to _hub_analysis2.txt")
