#!/usr/bin/env bash

# Start US market data collection

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
PID_FILE="$LOG_DIR/us_collector.pid"

mkdir -p "$LOG_DIR"

echo "Starting US market data collection..."
nohup "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/main_collector.py" --market US >> "$LOG_DIR/us_market.log" 2>&1 &
echo $! > "$PID_FILE"
echo "US collector started with PID $(cat "$PID_FILE")"
