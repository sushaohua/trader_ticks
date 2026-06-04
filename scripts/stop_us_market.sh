#!/usr/bin/env bash

# Stop US market data collection

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
PID_FILE="$LOG_DIR/us_collector.pid"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping US market data collection (PID $PID)..."
    kill "$PID"
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
      echo "Process still running, forcing kill..."
      kill -9 "$PID"
    fi
    rm -f "$PID_FILE"
    echo "US collector stopped."
    exit 0
  fi
  echo "PID file exists but process is not running, removing stale PID file."
  rm -f "$PID_FILE"
fi

echo "No running US collector found."
