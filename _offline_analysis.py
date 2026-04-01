import re

# Try multiple encodings
for enc in ['utf-16-le', 'utf-8', 'utf-8-sig', 'gbk', 'latin-1']:
    try:
        with open(r'd:\AutoTrade\tmp_backend_logs.txt', 'r', encoding=enc, errors='ignore') as f:
            content = f.read()
        if len(content) > 100:
            print(f"Read with encoding: {enc}, length: {len(content)}")
            break
    except:
        continue

lines = content.split('\n')
print(f'Total lines: {len(lines)}')

# Filter hub/daemon/trade lines  
hub_pat = re.compile(r'HubDaemon|HubAgent|HubBrain|cycle|open_position|place_order|execute_trade|tool_call|tool_result|wake|signal|ERROR|Traceback|Exception|daemon', re.IGNORECASE)
filtered = [l for l in lines if hub_pat.search(l) and 'HTTP/1.1' not in l]

# Write results
with open(r'd:\AutoTrade\_analysis_result.txt', 'w', encoding='utf-8') as f:
    f.write(f"Total lines: {len(lines)}\n")
    f.write(f"Hub/trade filtered lines: {len(filtered)}\n")
    f.write(f"First line: {lines[0][:150]}\n")
    f.write(f"Last line: {lines[-2][:150] if len(lines) > 1 else 'N/A'}\n\n")
    f.write("=== FILTERED HUB/TRADE LOGS ===\n")
    for l in filtered:
        f.write(l.strip() + '\n')

# Also check _current_logs.txt
try:
    with open(r'd:\AutoTrade\_current_logs.txt', 'r', encoding='utf-8', errors='ignore') as f:
        curr = f.read()
    curr_lines = curr.split('\n')
    curr_filtered = [l for l in curr_lines if hub_pat.search(l) and 'HTTP/1.1' not in l]
    f2 = open(r'd:\AutoTrade\_analysis_result.txt', 'a', encoding='utf-8')
    f2.write(f"\n\n=== _current_logs.txt ({len(curr_lines)} lines) ===\n")
    for l in curr_filtered:
        f2.write(l.strip() + '\n')
    f2.close()
except Exception as e:
    print(f"Error reading _current_logs.txt: {e}")

# Also check other log files
for logfile in ['_remote_logs.txt', '_remote_log2.txt', '_logs3.txt', 'non_info_logs.txt', '_backend_err.txt', 'tmp_errors.log']:
    try:
        with open(f'd:\\AutoTrade\\{logfile}', 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()
        log_lines = log_content.split('\n')
        log_filtered = [l for l in log_lines if hub_pat.search(l) and 'HTTP/1.1' not in l]
        if log_filtered:
            with open(r'd:\AutoTrade\_analysis_result.txt', 'a', encoding='utf-8') as f2:
                f2.write(f"\n\n=== {logfile} ({len(log_lines)} lines, {len(log_filtered)} matches) ===\n")
                for l in log_filtered:
                    f2.write(l.strip() + '\n')
    except Exception as e:
        print(f"Error reading {logfile}: {e}")

print("Analysis saved to _analysis_result.txt")
