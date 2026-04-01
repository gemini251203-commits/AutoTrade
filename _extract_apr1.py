import re

results = []

# Read _hub_logs.txt
with open(r'd:\AutoTrade\_hub_logs.txt', 'r', encoding='utf-8-sig', errors='ignore') as f:
    lines = f.readlines()

results.append(f'_hub_logs.txt: {len(lines)} lines')
for l in lines:
    l = l.strip()
    if l and '2026-04-01' in l:
        results.append(l[:300])

results.append('')

# Read _today_logs.txt
for enc in ['utf-16-le', 'utf-16', 'utf-8-sig', 'utf-8']:
    try:
        with open(r'd:\AutoTrade\_today_logs.txt', 'r', encoding=enc, errors='ignore') as f:
            content = f.read()
        if len(content) > 100:
            results.append(f'Read _today_logs.txt with {enc}')
            break
    except:
        continue

tlines = content.split('\n')
results.append(f'_today_logs.txt: {len(tlines)} lines')
for l in tlines:
    l = l.strip()
    if '2026-04-01' in l and 'HTTP/1.1' not in l:
        results.append(l[:300])

with open(r'd:\AutoTrade\_apr1_summary.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(results))

print(f'Saved {len(results)} lines to _apr1_summary.txt')
