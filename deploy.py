#!/usr/bin/env python3
"""TradingAgents-AShare 部署脚本

用法: python deploy.py

流程: 变更检测 → 按需构建 → 上传 → 按需重启 → 健康检查
"""

import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

import paramiko

# ---------- 配置 ----------
SERVER = "119.23.155.192"
USER = "root"
PASSWORD = "Qq121918="
REMOTE_DIR = "/opt/tradingagents"
BACKEND_DIRS = ["api", "tradingagents", "scheduler"]
BACKEND_PORT = 8088
KILL_TERM_TIMEOUT = 10   # SIGTERM 后等待秒数
KILL_FORCE_TIMEOUT = 5   # 再次等待后仍存活才 SIGKILL

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(PROJECT_DIR, ".deploy_state.json")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_commit": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def git_changed_dirs(last_commit):
    """对比 last_commit..HEAD，判断哪些目录有变更"""
    if not last_commit:
        return {"frontend": True, "backend": True}

    result = subprocess.run(
        f"git diff --name-only {last_commit} HEAD",
        capture_output=True, shell=True, cwd=PROJECT_DIR, text=True,
    )
    if result.returncode != 0:
        return {"frontend": True, "backend": True}

    files = [f for f in result.stdout.strip().split("\n") if f]
    changed = {"frontend": False, "backend": False}
    for f in files:
        if f.startswith("frontend/"):
            changed["frontend"] = True
        elif any(f.startswith(d + "/") for d in BACKEND_DIRS) or f == "pyproject.toml":
            changed["backend"] = True
    return changed


def build_frontend():
    """清理并重新构建前端"""
    frontend_dir = os.path.join(PROJECT_DIR, "frontend")
    dist_dir = os.path.join(frontend_dir, "dist")

    # 清理旧构建
    if os.path.exists(dist_dir):
        subprocess.run(f"rm -rf {dist_dir}", shell=True, cwd=frontend_dir)

    result = subprocess.run(
        "npm run build",
        cwd=frontend_dir, capture_output=True, shell=True,
    )
    if result.returncode != 0:
        print("[FAIL] 前端构建失败")
        print(result.stderr.decode()[-500:])
        sys.exit(1)


def upload_frontend(ssh_client):
    """打包 dist 目录 → SFTP 上传 tar.gz → 服务器解压"""
    dist_dir = os.path.join(PROJECT_DIR, "frontend", "dist")

    # 1. 写入临时文件（比 BytesIO+putfo 更可靠）
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    try:
        with tarfile.open(fileobj=tmp, mode="w:gz") as tar:
            tar.add(dist_dir, arcname="dist")
        tmp_path = tmp.name
        tmp.close()

        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        print(f"  上传前端 ({size_mb:.1f}MB) ...")

        remote_tar = "/tmp/deploy_frontend.tar.gz"

        # 2. 用独立 SFTP 连接上传，传完即关，确保数据刷盘
        sftp = ssh_client.open_sftp()
        sftp.put(tmp_path, remote_tar)
        sftp.close()

        # 3. 解压（此时 SFTP 已关闭，数据已落地）
        remote_dest = REMOTE_DIR + "/frontend"
        stdin, stdout, stderr = ssh_client.exec_command(
            f"rm -rf {remote_dest}/dist && "
            f"tar -xzf {remote_tar} -C {remote_dest} && "
            f"rm {remote_tar} && "
            f"echo OK"
        )
        out = stdout.read().decode()
        err = stderr.read().decode()
        if "OK" not in out:
            print(f"  [FAIL] 解压失败\n  stdout: {out}\n  stderr: {err}")
            sys.exit(1)
        print("  [OK] 前端上传完成")
    finally:
        os.unlink(tmp_path)


def server_reset_code(ssh_client):
    """服务器重置代码到当前分支（避免合并冲突）"""
    # 获取当前分支名，推送到 origin 后用同样的分支部署
    current_branch = subprocess.run(
        "git branch --show-current",
        capture_output=True, shell=True, cwd=PROJECT_DIR, text=True,
    ).stdout.strip()
    remote_ref = f"origin/{current_branch}" if current_branch else "origin/main"
    print(f"  部署分支: {remote_ref}")
    stdin, stdout, stderr = ssh_client.exec_command(
        f"cd {REMOTE_DIR} && "
        f"git fetch origin && "
        f"git reset --hard {remote_ref} 2>&1"
    )
    out = stdout.read().decode().strip()
    print("  git: " + out.replace("\n", "\n  git: "))


def kill_backend(ssh_client):
    """停止后端服务 — 三级强制清理 + 端口验证

    Phase 1: pkill SIGTERM → 等 10s → 检查
    Phase 2: 仍存活 → 再等 5s → 检查
    Phase 3: 仍存活 → pkill -9 SIGKILL → 验证端口释放
    """
    print("  停止后端...")

    kill_script = f'''#!/bin/bash
set -e
PORT={BACKEND_PORT}
TERM_TIMEOUT={KILL_TERM_TIMEOUT}
FORCE_TIMEOUT={KILL_FORCE_TIMEOUT}

# ---- 查找占用端口的 PID ----
PIDS=$(ss -tlnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\\K[0-9]+' | sort -u)
if [ -z "$PIDS" ]; then
    PIDS=$(pgrep -f 'uvicorn api.main' 2>/dev/null || true)
fi

if [ -z "$PIDS" ]; then
    echo "PORT_FREE"
    exit 0
fi

echo "FOUND_PIDS $PIDS"

# ---- Phase 1: SIGTERM ----
for pid in $PIDS; do
    kill -TERM "$pid" 2>/dev/null || true
done

# 等待并检测
for i in $(seq 1 $TERM_TIMEOUT); do
    sleep 1
    ALIVE=""
    for pid in $PIDS; do
        kill -0 "$pid" 2>/dev/null && ALIVE="$ALIVE $pid"
    done
    if [ -z "$ALIVE" ]; then
        echo "TERM_OK"
        break
    fi
    PIDS="$ALIVE"
done

# ---- Phase 2: 额外等待（进程可能在 flush 数据） ----
if [ -n "$PIDS" ]; then
    echo "WAITING $PIDS"
    sleep $FORCE_TIMEOUT
    ALIVE=""
    for pid in $PIDS; do
        kill -0 "$pid" 2>/dev/null && ALIVE="$ALIVE $pid"
    done
    if [ -z "$ALIVE" ]; then
        echo "WAIT_OK"
        PIDS=""
    else
        PIDS="$ALIVE"
    fi
fi

# ---- Phase 3: SIGKILL 兜底 ----
if [ -n "$PIDS" ]; then
    echo "FORCE_KILL $PIDS"
    for pid in $PIDS; do
        kill -9 "$pid" 2>/dev/null || true
    done
    sleep 2
    ALIVE=""
    for pid in $PIDS; do
        kill -0 "$pid" 2>/dev/null && ALIVE="$ALIVE $pid"
    done
    if [ -n "$ALIVE" ]; then
        echo "STUCK $ALIVE"
        exit 1
    fi
    echo "FORCE_OK"
fi

# ---- 验证端口已释放 ----
for i in $(seq 1 6); do
    IN_USE=$(ss -tlnp 2>/dev/null | grep ":$PORT " | wc -l)
    if [ "$IN_USE" -eq 0 ]; then
        echo "PORT_FREE"
        exit 0
    fi
    sleep 0.5
done
echo "PORT_STUCK"
exit 1
'''

    stdin, stdout, stderr = ssh_client.exec_command(kill_script)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()

    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "FOUND_PIDS" in line:
            print(f"    发现进程: {line.replace('FOUND_PIDS ', '')}")
        elif "TERM_OK" in line:
            print("    [OK] SIGTERM 优雅关闭成功")
        elif "WAITING" in line:
            print(f"    等待进程flush: {line.replace('WAITING ', '')}")
        elif "WAIT_OK" in line:
            print("    [OK] 进程在等待后退出")
        elif "FORCE_KILL" in line:
            print(f"    [WARN] 强制终止: {line.replace('FORCE_KILL ', '')}")
        elif "FORCE_OK" in line:
            print("    [OK] 强制终止完成")
        elif "PORT_FREE" in line:
            print(f"    [OK] 端口 {BACKEND_PORT} 已释放")
        elif "STUCK" in line:
            pids = line.replace("STUCK ", "")
            print(f"    [FAIL] 进程无法终止! PID: {pids}")
            print(f"    请手动登录服务器执行: kill -9 {pids}")
        elif "PORT_STUCK" in line:
            print(f"    [FAIL] 端口 {BACKEND_PORT} 仍被占用，进程清理失败!")

    if err:
        print(f"    [WARN] stderr: {err}")

    if "STUCK" in out or "PORT_STUCK" in out:
        print("  [ABORT] 端口清理失败，取消部署以保护数据安全")
        sys.exit(1)

    if "PORT_FREE" in out:
        return True


def start_backend(ssh_client):
    """启动后端服务（启动前验证端口已释放）"""
    # 启动前再次确认端口空闲
    stdin, stdout, stderr = ssh_client.exec_command(
        f"ss -tlnp 2>/dev/null | grep ':{BACKEND_PORT} ' | wc -l"
    )
    in_use = stdout.read().decode().strip()
    if in_use != "0":
        print(f"  [FAIL] 端口 {BACKEND_PORT} 仍被占用，无法启动后端")
        sys.exit(1)

    print("  启动后端...")
    ssh_client.exec_command(
        f"cd {REMOTE_DIR} && "
        f"nohup /usr/local/bin/python3.10 -m uvicorn api.main:app "
        f"--host 0.0.0.0 --port {BACKEND_PORT} --log-level warning "
        f"> logs/backend.log 2>&1 &"
    )
    time.sleep(1)

    # 验证进程已启动
    stdin, stdout, stderr = ssh_client.exec_command(
        f"pgrep -f 'uvicorn api.main' | wc -l"
    )
    count = stdout.read().decode().strip()
    if count == "0":
        print("  [FAIL] 后端进程启动失败，检查 logs/backend.log")
        sys.exit(1)
    print(f"  [OK] 后端进程已启动 (PID数: {count})")


def setup_nginx(ssh_client):
    """配置 nginx 反向代理"""
    nginx_conf = '''server {
    listen 80;
    server_name _;

    root /opt/tradingagents/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /v1/ {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
    }

    location /healthz {
        proxy_pass http://127.0.0.1:8088;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8088;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8088;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
'''
    sftp = ssh_client.open_sftp()
    with sftp.open("/etc/nginx/conf.d/tradingagents.conf", "w") as f:
        f.write(nginx_conf)
    sftp.close()

    # 测试并重载 nginx
    stdin, stdout, stderr = ssh_client.exec_command("nginx -t 2>&1")
    test_out = stdout.read().decode()
    if "successful" in test_out:
        ssh_client.exec_command("nginx -s reload 2>/dev/null || systemctl restart nginx")
        print("  [OK] nginx 配置已更新")
    else:
        print(f"  [WARN] nginx 配置测试失败: {test_out}")


def wait_for_health(timeout=120):
    """健康检查，等待后端就绪（通过 nginx 代理）"""
    url = f"http://{SERVER}/healthz"
    deadline = time.time() + timeout
    printed = False
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            if resp.status == 200:
                if printed:
                    print()
                return True
        except Exception:
            pass
        remaining = int(deadline - time.time())
        print(f"\r  等待后端启动... ({remaining}s)", end="")
        printed = True
        time.sleep(3)
    if printed:
        print()
    return False


def smoke_test():
    """验证关键接口可用"""
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")

    # 测试 K 线接口（通过 nginx 代理）
    url = f"http://{SERVER}/v1/market/kline?symbol=000001.SH&start_date={month_ago}&end_date={today}&period=weekly"
    try:
        resp = urllib.request.urlopen(url, timeout=15)
        data = json.loads(resp.read().decode())
        count = len(data.get("candles", []))
        ok = 3 <= count <= 12
        status = "[OK]" if ok else "[FAIL]"
        print(f"  {status} K线接口: {count} 条")
        return ok
    except Exception as e:
        print(f"  [FAIL] 冒烟测试: {e}")
        return False


def verify_nginx():
    """验证 nginx 代理正常"""
    try:
        # 前端
        resp = urllib.request.urlopen(f"http://{SERVER}/", timeout=10)
        if resp.status != 200:
            print("  [FAIL] nginx 前端代理")
            return False

        # API
        req = urllib.request.Request(
            f"http://{SERVER}/v1/auth/request-code",
            data=json.dumps({"email": "test@test.com"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        # 403 说明 API 正常（只是邮箱未授权）
        print("  [OK] nginx 代理正常")
        return True
    except Exception as e:
        # 403 也说明 API 可达
        if "403" in str(e):
            print("  [OK] nginx 代理正常")
            return True
        print(f"  [FAIL] nginx 验证: {e}")
        return False


def main():
    # ---- 1. 变更检测 ----
    state = load_state()
    changes = git_changed_dirs(state.get("last_commit"))
    need_frontend = changes["frontend"]
    need_backend = changes["backend"]

    if not need_frontend and not need_backend:
        print("[SKIP] 无文件变更，跳过部署")
        return

    labels = []
    if need_frontend:
        labels.append("前端")
    if need_backend:
        labels.append("后端")
    print(f">>> 变更: {'+'.join(labels)}")

    # ---- 2. 构建 ----
    if need_frontend:
        print(">>> 构建前端...")
        build_frontend()
        print("[OK] 前端构建完成")

    # ---- 3. 连接服务器 ----
    print(">>> 连接服务器...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USER, password=PASSWORD)
    sftp = client.open_sftp()

    try:
        # ---- 4a. 上传前端 ----
        if need_frontend:
            upload_frontend(client)
            setup_nginx(client)

        # ---- 4b. 后端部署 ----
        if need_backend:
            print(">>> 服务器更新代码...")
            kill_backend(client)
            server_reset_code(client)
            start_backend(client)

    finally:
        sftp.close()
        client.close()

    # ---- 5. 健康检查 ----
    if need_backend:
        print(">>> 等待后端启动...")
        if not wait_for_health():
            print("[FAIL] 后端启动超时")
            sys.exit(1)
        print("[OK] 后端已就绪")

        if not smoke_test():
            print("[FAIL] 冒烟测试未通过")
            sys.exit(1)
        print("[OK] 冒烟测试通过")

    # ---- 6. 验证 nginx ----
    if need_frontend:
        print(">>> 验证 nginx 代理...")
        if not verify_nginx():
            print("[WARN] nginx 验证失败，请手动检查")

    # 记录部署状态
    current = subprocess.run(
        "git rev-parse HEAD",
        capture_output=True, shell=True, cwd=PROJECT_DIR, text=True,
    ).stdout.strip()
    save_state({"last_commit": current})
    print(f"\n[DONE] 部署完成! http://{SERVER}")


if __name__ == "__main__":
    main()
