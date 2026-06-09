#!/usr/bin/env bash

set -e

# 获取脚本所在项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STOCK_DATA_DIR="$HOME/stock_data"
ARCHIVE_DIR="$STOCK_DATA_DIR/archive"
REPORT_DIR="$STOCK_DATA_DIR/reports"

echo "📂 正在初始化配置环境..."
echo "项目根目录: $PROJECT_ROOT"
echo "数据存储根目录: $STOCK_DATA_DIR"

# 1. 创建存储目录
mkdir -p "$ARCHIVE_DIR"
mkdir -p "$REPORT_DIR"
echo "✅ 存储目录已创建: $ARCHIVE_DIR, $REPORT_DIR"

# 2. 生成 futu_settings.json 配置文件
CONFIG_FILE="$STOCK_DATA_DIR/futu_settings.json"
cat <<EOF > "$CONFIG_FILE"
{
    "futu_opend": {
        "host": "127.0.0.1",
        "port": 11111
    },
    "storage": {
        "base_archive_dir": "$ARCHIVE_DIR",
        "base_report_dir": "$REPORT_DIR",
        "flush_threshold": 200,
        "flush_interval_seconds": 10,
        "compression": "snappy"
    }
}
EOF
echo "✅ 配置文件已写入: $CONFIG_FILE"

# 3. 创建本地软链接覆盖配置
LOCAL_LINK="$PROJECT_ROOT/configs/futu_settings.local.json"
ln -sf "$CONFIG_FILE" "$LOCAL_LINK"
echo "✅ 软链接已创建: $LOCAL_LINK -> $CONFIG_FILE"

echo "🎉 配置初始化完成！"
