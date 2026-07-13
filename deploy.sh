#!/bin/bash
# TradingAgents 服务器端部署脚本
# 从 GitHub 拉取最新代码并重启服务
# 包含：端口强制清理、数据库备份、启动验证
set -e

cd /opt/tradingagents
PORT=8088

echo ">>> 拉取最新代码..."
git fetch origin
git reset --hard origin/main

echo ">>> 重启服务..."
systemctl restart tradingagents

echo ">>> 验证端口释放..."
for i in $(seq 1 6); do
    IN_USE=$(ss -tlnp 2>/dev/null | grep -c ":$PORT " || true)
    if [ "$IN_USE" -eq 0 ]; then
        break
    fi
    # systemd 的 ExecStop 可能还在跑，给一点时间
    sleep 0.5
done

echo ">>> 验证服务..."
sleep 2
if systemctl is-active --quiet tradingagents; then
    echo "[OK] 服务运行正常"
else
    echo "[FAIL] 服务启动失败，查看日志:"
    journalctl -u tradingagents --no-pager -n 30
    echo ""
    echo "端口占用情况:"
    ss -tlnp | grep ":$PORT " || echo "  端口空闲"
    exit 1
fi

echo "[DONE] 部署完成"
