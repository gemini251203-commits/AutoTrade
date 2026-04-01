import subprocess

cmd = ['ssh', '-T', '-o', 'ConnectTimeout=10', 'root@45.77.26.211', 'docker ps && echo \"--- LOGS ---\" && docker logs --tail 200 autotrade-backend']
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
out, err = p.communicate()

print("STDOUT:")
print(out.decode('utf-8', errors='ignore'))
print("\nSTDERR:")
print(err.decode('utf-8', errors='ignore'))
