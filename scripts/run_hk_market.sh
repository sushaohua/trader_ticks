#!/usr/bin/env bash

# Start HK market data collection

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
PID_FILE="$LOG_DIR/hk_collector.pid"

mkdir -p "$LOG_DIR"

echo "Starting HK market data collection..."
nohup "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/main_collector.py" --market HK >> "$LOG_DIR/hk_market.log" 2>&1 &
echo $! > "$PID_FILE"
echo "HK collector started with PID $(cat "$PID_FILE")"
