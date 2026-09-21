#!/usr/bin/env python3
"""TradingAgents-AShare 部署脚本

用法: python deploy.py

流程: 变更检测 → 按需构建 → 上传 → 按需重启 → 健康检查
"""

import json
import os
import socket
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
DEP_FILES = {"requirements.txt", "pyproject.toml", "uv.lock"}  # 变化时才需要重装依赖

# ---- 超时保护（防止网络抖动/远程命令阻塞导致部署脚本永久卡死）----
SSH_CONNECT_TIMEOUT = 30    # SSH 建立连接超时（秒）
SSH_CMD_TIMEOUT = 120       # 远程命令执行超时（秒）
SSH_PIP_TIMEOUT = 600       # pip install 超时（秒，依赖安装可能较慢）
SSH_SFTP_TIMEOUT = 300      # SFTP 上传超时（秒）

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


def run_remote(ssh_client, cmd, timeout=SSH_CMD_TIMEOUT):
    """带超时执行远程命令，返回 (stdout, stderr) 字符串。

    超时抛 socket.timeout，由 main 的统一异常处理兜底，避免脚本永久挂起。
    """
    stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=timeout)
    return stdout.read().decode(), stderr.read().decode()


def git_changed_dirs(last_commit):
    """对比 last_commit..HEAD，判断前端/后端/依赖是否有变更"""
    if not last_commit:
        return {"frontend": True, "backend": True, "deps": True}

    result = subprocess.run(
        f"git diff --name-only {last_commit} HEAD",
        capture_output=True, shell=True, cwd=PROJECT_DIR, text=True,
    )
    if result.returncode != 0:
        return {"frontend": True, "backend": True, "deps": True}

    files = [f for f in result.stdout.strip().split("\n") if f]
    changed = {"frontend": False, "backend": False, "deps": False}
    for f in files:
        if f.startswith("frontend/"):
            changed["frontend"] = True
        elif any(f.startswith(d + "/") for d in BACKEND_DIRS):
            changed["backend"] = True
        if f in DEP_FILES:
            changed["deps"] = True
            if f == "pyproject.toml":
                changed["backend"] = True  # pyproject 也可能影响运行，保守重部署
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
        sftp.get_channel().settimeout(SSH_SFTP_TIMEOUT)
        sftp.put(tmp_path, remote_tar)
        sftp.close()

        # 3. 解压（此时 SFTP 已关闭，数据已落地）
        remote_dest = REMOTE_DIR + "/frontend"
        out, err = run_remote(ssh_client,
            f"rm -rf {remote_dest}/dist && "
            f"tar -xzf {remote_tar} -C {remote_dest} && "
            f"rm {remote_tar} && "
            f"echo OK")
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
    out, _ = run_remote(ssh_client,
        f"cd {REMOTE_DIR} && "
        f"git fetch origin && "
        f"git reset --hard {remote_ref} 2>&1")
    out = out.strip()
    print("  git: " + out.replace("\n", "\n  git: "))


def install_dependencies(ssh_client):
    """安装 Python 依赖"""
    print("  安装依赖...")
    out, err = run_remote(ssh_client,
        f"cd {REMOTE_DIR} && "
        f"/usr/local/bin/python3.10 -m pip install -r requirements.txt --quiet 2>&1",
        timeout=SSH_PIP_TIMEOUT)
    out = out.strip()
    err = err.strip()
    if out:
        print(f"    {out[-200:]}")
    if err and "error" in err.lower():
        print(f"    [WARN] {err[-200:]}")
    print("  [OK] 依赖安装完成")


def restart_backend(ssh_client):
    """通过 systemd 重启后端（tradingagents.service 托管）。

    生产后端由 systemd 管理（Restart=always），手动 kill + nohup 会与之冲突，
    造成 10 秒一次的自毁死循环；正确做法是 systemctl restart 回归单实例。
    """
    print("  重启后端 (systemctl restart tradingagents.service)...")
    out, err = run_remote(ssh_client,
        "systemctl restart tradingagents.service && echo RESTART_OK",
        timeout=SSH_CMD_TIMEOUT)
    out = out.strip()
    err = err.strip()
    if "RESTART_OK" not in out:
        print(f"  [FAIL] systemd 重启失败\n  stdout: {out}\n  stderr: {err}")
        sys.exit(1)
    print("  [OK] systemd 已重启后端")


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
    sftp.get_channel().settimeout(SSH_SFTP_TIMEOUT)
    with sftp.open("/etc/nginx/conf.d/tradingagents.conf", "w") as f:
        f.write(nginx_conf)
    sftp.close()

    # 测试并重载 nginx
    test_out, _ = run_remote(ssh_client, "nginx -t 2>&1")
    if "successful" in test_out:
        run_remote(ssh_client, "nginx -s reload 2>/dev/null || systemctl restart nginx")
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
    skip_deps = "--skip-deps" in sys.argv  # 手动强制跳过依赖安装

    # ---- 1. 变更检测 ----
    state = load_state()
    changes = git_changed_dirs(state.get("last_commit"))
    need_frontend = changes["frontend"]
    need_backend = changes["backend"]
    need_deps = changes.get("deps", False) and not skip_deps

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
    try:
        client.connect(
            SERVER, username=USER, password=PASSWORD,
            timeout=SSH_CONNECT_TIMEOUT,
            banner_timeout=SSH_CONNECT_TIMEOUT,
            auth_timeout=SSH_CONNECT_TIMEOUT,
        )
    except (socket.timeout, paramiko.SSHException, EOFError, OSError) as e:
        print(f"[FAIL] 无法连接服务器 {SERVER}: {e}")
        print("  请检查网络与服务器状态后重试。")
        sys.exit(1)

    sftp = client.open_sftp()

    try:
        # ---- 4a. 上传前端 ----
        if need_frontend:
            upload_frontend(client)
            setup_nginx(client)

        # ---- 4b. 后端部署 ----
        if need_backend:
            print(">>> 服务器更新代码...")
            server_reset_code(client)
            if need_deps:
                install_dependencies(client)
            else:
                print("  依赖未变更，跳过安装")
            restart_backend(client)

    except (socket.timeout, paramiko.SSHException, EOFError, OSError) as e:
        print(f"\n[FAIL] 部署中断（连接/命令超时或网络异常）: {e}")
        print("  生产服务可能处于旧版本或部分更新状态，请登录服务器检查后重试。")
        sys.exit(1)
    finally:
        try:
            sftp.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

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
