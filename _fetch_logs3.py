import subprocess

# Smaller request - just last 200 lines
cmd = [
    'ssh', '-T', '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=5', 
    'root@45.77.26.211',
    "docker logs --tail 200 autotrade-backend 2>&1 | head -200"
]

try:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    with open(r'd:\AutoTrade\_hub_analysis2.txt', 'w', encoding='utf-8') as f:
        f.write(r.stdout)
        if r.stderr:
            f.write('\n---STDERR---\n' + r.stderr)
    print(f"Done. Got {len(r.stdout)} bytes, {r.stdout.count(chr(10))} lines")
    print(f"Return code: {r.returncode}")
except Exception as e:
    print(f"Error: {e}")
