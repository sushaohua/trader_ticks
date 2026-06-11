#!/usr/bin/env bash

set -e

# 获取脚本所在项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_CRON_FILE="/tmp/trader_ticks_cron"

echo "⏰ 正在配置 crontab 定时任务..."
echo "项目根目录: $PROJECT_ROOT"

# 使用 Python 动态检测时区并生成 crontab 内容
python3 - <<EOF "$PROJECT_ROOT" "$TEMP_CRON_FILE"
import sys
import time

project_root = sys.argv[1]
temp_file = sys.argv[2]

# 获取当前时区偏离 UTC 的小时数 (time.timezone 西区为正，东区为负，所以取负数)
# 并考虑夏令时
tz_offset = -time.timezone / 3600.0 if time.daylight == 0 else -time.altzone / 3600.0

print(f"  -> 检测到当前系统时区偏离量: {tz_offset:+.1f} 小时")

cron_lines = []
if abs(tz_offset - 8.0) < 0.5:
    print("  -> 匹配到北京时间 (UTC+8) 时区，使用标准时间配置")
    cron_lines = [
        f"25 21 * * 1-5 {project_root}/scripts/run_us_market.sh",
        f"5 4 * * 2-6 {project_root}/scripts/stop_us_market.sh",
        f"30 4 * * 2-6 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market US >> {project_root}/data/logs/cron_daily_stats.log 2>&1",
        f"25 9 * * 1-5 {project_root}/scripts/run_hk_market.sh",
        f"5 16 * * 1-5 {project_root}/scripts/stop_hk_market.sh",
        f"30 16 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market HK >> {project_root}/data/logs/cron_daily_stats.log 2>&1",
        f"30 15 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market CN >> {project_root}/data/logs/cron_daily_stats.log 2>&1"
    ]
elif abs(tz_offset - 0.0) < 0.5:
    print("  -> 匹配到零时区 (UTC/GMT)，自动换算 cron 时间")
    cron_lines = [
        f"25 13 * * 1-5 {project_root}/scripts/run_us_market.sh",
        f"5 20 * * 1-5 {project_root}/scripts/stop_us_market.sh",
        f"30 20 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market US >> {project_root}/data/logs/cron_daily_stats.log 2>&1",
        f"25 1 * * 1-5 {project_root}/scripts/run_hk_market.sh",
        f"5 8 * * 1-5 {project_root}/scripts/stop_hk_market.sh",
        f"30 8 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market HK >> {project_root}/data/logs/cron_daily_stats.log 2>&1",
        f"30 7 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market CN >> {project_root}/data/logs/cron_daily_stats.log 2>&1"
    ]
else:
    print("  -> 其他时区，默认采用北京时间配置并声明 CRON_TZ")
    cron_lines = [
        "CRON_TZ=Asia/Shanghai",
        f"25 21 * * 1-5 {project_root}/scripts/run_us_market.sh",
        f"5 4 * * 2-6 {project_root}/scripts/stop_us_market.sh",
        f"30 4 * * 2-6 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market US >> {project_root}/data/logs/cron_daily_stats.log 2>&1",
        f"25 9 * * 1-5 {project_root}/scripts/run_hk_market.sh",
        f"5 16 * * 1-5 {project_root}/scripts/stop_hk_market.sh",
        f"30 16 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market HK >> {project_root}/data/logs/cron_daily_stats.log 2>&1",
        f"30 15 * * 1-5 {project_root}/venv/bin/python {project_root}/daily_stats_collector.py --market CN >> {project_root}/data/logs/cron_daily_stats.log 2>&1"
    ]

cron_content = "# Auto-generated cron schedule for trader_ticks\n" + "\n".join(cron_lines) + "\n"
with open(temp_file, "w") as f:
    f.write(cron_content)
EOF

# 安装生成的 crontab 配置文件
echo "  -> 写入临时配置文件: $TEMP_CRON_FILE"
cat "$TEMP_CRON_FILE"
crontab "$TEMP_CRON_FILE"
rm -f "$TEMP_CRON_FILE"

echo "✅ Crontab 定时任务已成功更新并载入！"
