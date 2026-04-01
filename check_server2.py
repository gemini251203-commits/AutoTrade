import subprocess
cmd = ['ssh', '-T', '-o', 'ConnectTimeout=10', 'root@45.77.26.211', 'docker ps && echo \"--- LOGS ---\" && docker logs --tail 200 autotrade-backend']
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
out, err = p.communicate()
with open("d:\\AutoTrade\\server_check_output.txt", "w", encoding='utf-8') as f:
    f.write("STDOUT:\n")
    f.write(out.decode('utf-8', errors='ignore'))
    f.write("\nSTDERR:\n")
    f.write(err.decode('utf-8', errors='ignore'))
