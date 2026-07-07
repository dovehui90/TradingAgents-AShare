import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('119.23.155.192', username='root', password='Qq121918=', timeout=15)

# Upload query script
sftp = client.open_sftp()
sftp.put(r'd:\AIProjects\TradingAgents-AShare\_tmp_query.py', '/tmp/query.py')
sftp.close()

# Execute
stdin, stdout, stderr = client.exec_command('/usr/local/bin/python3.10 /tmp/query.py')
out = stdout.read().decode()
err = stderr.read().decode()
print(out)
if err:
    print("STDERR:", err[:500])

client.close()
