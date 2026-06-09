#!/usr/bin/env bash

set -e

# 获取脚本所在项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STOCK_DATA_DIR="$HOME/stock_data"
CONFIGS_DEST_DIR="$STOCK_DATA_DIR/configs"

echo "📂 正在初始化配置与存储环境..."
echo "项目根目录: $PROJECT_ROOT"
echo "数据存储根目录: $STOCK_DATA_DIR"

# 1. 创建相关存储与配置目录
mkdir -p "$STOCK_DATA_DIR/archive"
mkdir -p "$STOCK_DATA_DIR/reports"
mkdir -p "$CONFIGS_DEST_DIR"
echo "✅ 基础目录已就绪: archive, reports, configs"

# 2. 从 configs.template 复制不存在的配置文件（防覆盖用户自选与配置）
TEMPLATE_DIR="$PROJECT_ROOT/configs.template"
if [ -d "$TEMPLATE_DIR" ]; then
    echo "⚙️ 正在从模板初始化配置文件..."
    for file in "$TEMPLATE_DIR"/*; do
        if [ -f "$file" ]; then
            filename=$(basename "$file")
            # 排除遗留的 local 软链接配置文件
            if [ "$filename" != "futu_settings.local.json" ]; then
                dest_file="$CONFIGS_DEST_DIR/$filename"
                if [ ! -f "$dest_file" ]; then
                    cp "$file" "$dest_file"
                    echo "   -> [NEW] 初始化生成配置文件: $filename"
                else
                    echo "   -> [KEEP] 保留已存在的自定义配置: $filename"
                fi
            fi
        fi
    done
else
    echo "⚠️ 警告: 未找到配置模板目录 configs.template"
fi

# 3. 创建 configs 软链接对齐业务代码
LOCAL_LINK="$PROJECT_ROOT/configs"
if [ -d "$LOCAL_LINK" ] && [ ! -L "$LOCAL_LINK" ]; then
    echo "⚠️ 发现物理目录 $LOCAL_LINK，正在清理以替换为软链接..."
    rm -rf "$LOCAL_LINK"
fi

ln -sfn "$CONFIGS_DEST_DIR" "$LOCAL_LINK"
echo "✅ 软链接已创建: $LOCAL_LINK -> $CONFIGS_DEST_DIR"

echo "🎉 配置与业务解耦初始化全部完成！"
