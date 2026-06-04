#!/bin/bash

# Start US market data collection

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Starting US market data collection..."
python3 "$PROJECT_DIR/main_collector.py" --market US
