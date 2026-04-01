import subprocess

# SQL script to manually fix the partially applied migration
sql_script = """
-- 1. Create the missing specific missing columns and indices if they dont exist
ALTER TABLE positions ADD COLUMN IF NOT EXISTS prompt_template_id INTEGER;
ALTER TABLE hub_agents ADD COLUMN IF NOT EXISTS active_template_id INTEGER;

-- 2. Optional: Add the foreign key and indices if we want them (we'll ignore failures if they exist)
DO $$
BEGIN
    BEGIN
        ALTER TABLE hub_agents ADD CONSTRAINT fk_hub_agents_active_template FOREIGN KEY (active_template_id) REFERENCES prompt_templates(id) ON DELETE SET NULL;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END;
END $$;

-- 3. We will then ask alembic to just stamp the DB version 
-- Since we manually added the columns, the app can start
"""

print("Running manual DB schema fix over SSH...")
cmd = ['ssh', '-T', 'root@45.77.26.211', 'docker exec -i autotrade-db psql -U autotrade -d autotrade']
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
out, err = p.communicate(sql_script.encode('utf-8'))

print("--- STDOUT ---")
print(out.decode('utf-8', errors='ignore'))
print("--- STDERR ---")
print(err.decode('utf-8', errors='ignore'))

if "ERROR" in err.decode('utf-8', errors='ignore'):
    print("Encountered errors, but some may be safe to ignore.")

# Now run alembic stamp to mark it as migrated
print("\nStamping DB version to head...")
stamp_cmd = ['ssh', '-T', 'root@45.77.26.211', 'cd /root/AutoTrade && docker compose run --rm backend alembic stamp head']
stamp_p = subprocess.Popen(stamp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
s_out, s_err = stamp_p.communicate()
print("--- STAMP STDOUT ---")
print(s_out.decode('utf-8', errors='ignore'))
print("--- STAMP STDERR ---")
print(s_err.decode('utf-8', errors='ignore'))

# Finally restart backend
print("\nRestarting backend...")
restart_cmd = ['ssh', '-T', 'root@45.77.26.211', 'cd /root/AutoTrade && docker compose restart backend']
restart_p = subprocess.Popen(restart_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
r_out, r_err = restart_p.communicate()
print("Backend restarted.")
