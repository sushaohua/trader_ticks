#!/usr/bin/env bash

# Start HK market data collection

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
PID_FILE="$LOG_DIR/hk_collector.pid"

mkdir -p "$LOG_DIR"

# 🔥 改进: 使用绝对路径启动，避免配置文件找不到
# 获取绝对路径后再启动，确保相对路径解析正确
echo "Starting HK market data collection..."
nohup bash -c "cd '$PROJECT_DIR' && '$PROJECT_DIR/venv/bin/python' -u '$PROJECT_DIR/main_collector.py' --market HK" >> "$LOG_DIR/hk_market.log" 2>&1 &
PID=$!
echo $PID > "$PID_FILE"
echo "HK collector started with PID $PID (Log: $LOG_DIR/hk_market.log)"
