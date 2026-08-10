#!/bin/bash
# TradingAgents 健康检查 - 每5分钟 cron 执行
LOG=/opt/tradingagents/logs/healthcheck.log
TS=$(date '+%Y-%m-%d %H:%M:%S')

# 1. 后端存活检查
if ! curl -sf http://localhost:8088/healthz > /dev/null 2>&1; then
    echo "[$TS] ALERT: Backend health check FAILED" >> $LOG
    systemctl restart tradingagents 2>> $LOG
    echo "[$TS] Attempted restart" >> $LOG
fi

# 2. 磁盘检查
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK_PCT" -gt 90 ]; then
    echo "[$TS] ALERT: Disk usage ${DISK_PCT}%" >> $LOG
fi

# 3. 日志轮转（保留7天，防止 messages 再次膨胀）
find /var/log -name "messages-*" -mtime +7 -delete 2>/dev/null
