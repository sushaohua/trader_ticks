#!/usr/bin/env bash

set -e

# 获取脚本所在项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 开始一键部署至服务器 yysrv..."

# 1. 检查本地是否有未提交的修改
if [ -n "$(git status --porcelain)" ]; then
    echo "❌ 部署终止: 本地工作区存在未提交的改动！"
    echo "请先使用 'git commit -am \"your message\"' 提交修改，以保持本地与 GitHub 仓库一致。"
    exit 1
fi

# 2. 检查是否有未推送的提交
UNPUSHED=$(git log origin/main..main --oneline)
if [ -n "$UNPUSHED" ]; then
    echo "⚠️ 发现未推送的本地提交，正在自动推送至 GitHub..."
    git push origin main
    echo "✅ 成功推送本地代码至 GitHub。"
else
    echo "✅ 本地工作区与 GitHub 保持一致。"
fi

echo "==========================================="
echo "🔌 正在通过 SSH 连接远程服务器 yysrv 并部署..."
echo "==========================================="

# 在远程服务器上执行的核心部署命令
ssh yysrv "bash -s" <<'EOF'
set -e
cd /home/sushaohua/code/trader_ticks

echo "📥 1. 正在拉取 GitHub 上的最新代码..."
git fetch origin
git reset --hard origin/main
git pull origin main
echo "✅ 远程代码已同步到最新状态。"

echo "⚙️ 2. 正在初始化远程配置..."
bash scripts/setup_config.sh

echo "⏰ 3. 正在更新远程定时任务 (crontab)..."
bash scripts/setup_cron.sh

echo "🔄 4. 正在检查并优雅重启数据收集进程..."
# 检测正在运行的收集器
RESTARTED=0
for pid_file in data/logs/*_collector.pid; do
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        filename=$(basename "$pid_file")
        market_prefix="${filename%_collector.pid}"
        MARKET=$(echo "$market_prefix" | tr '[:lower:]' '[:upper:]')
        if kill -0 "$PID" 2>/dev/null; then
            echo "   -> 发现正在运行的 ${MARKET} 收集器 (PID: $PID)，触发优雅重启..."
            # 获取对应的停止和启动脚本名称
            lower_market=$(echo "$MARKET" | tr '[:upper:]' '[:lower:]')
            stop_script="scripts/stop_${lower_market}_market.sh"
            run_script="scripts/run_${lower_market}_market.sh"
            
            if [ -f "$stop_script" ] && [ -f "$run_script" ]; then
                bash "$stop_script"
                bash "$run_script"
                RESTARTED=1
            else
                echo "   ❌ 找不到启动/停止脚本，无法重启 ${MARKET} 收集器"
            fi
        else
            echo "   -> PID 文件 $pid_file 存在但进程未运行，清除无用 PID 文件。"
            rm -f "$pid_file"
        fi
    fi
done

if [ $RESTARTED -eq 0 ]; then
    echo "   -> 当前未检测到正在运行的收集器，无需重启进程。"
fi

echo "🏥 5. 正在进行部署后健康检查..."
# 检查 Futu OpenD 通信
echo "   -> 验证远程 Futu OpenD 连接..."
source venv/bin/activate
python3 -c "
from futu import *
try:
    q = OpenQuoteContext(host='127.0.0.1', port=11111)
    ret, state = q.get_global_state()
    q.close()
    if ret == 0:
        is_logined = state.get('login_status') == '1' or state.get('qot_logined') is True
        if is_logined:
            print('      ✅ OpenD 状态检查通过: 连接已就绪，已成功登录富途服务器。')
            print(f'      详细状态: {state}')
        else:
            print('      ❌ OpenD 状态检查异常 (未登录): ', state)
    else:
        print('      ❌ OpenD 状态检查异常 (获取状态失败): ', ret, state)
except Exception as e:
    print('      ❌ 无法连接 OpenD: ', e)
"

# 检查可能刚刚重启的进程状态
for pid_file in data/logs/*_collector.pid; do
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        filename=$(basename "$pid_file")
        market_prefix="${filename%_collector.pid}"
        MARKET=$(echo "$market_prefix" | tr '[:lower:]' '[:upper:]')
        lower_market=$(echo "$MARKET" | tr '[:upper:]' '[:lower:]')
        if kill -0 "$PID" 2>/dev/null; then
            echo "   ✅ ${MARKET} 收集器进程正常运行 (PID: $PID)"
            echo "   -> 最近的 5 行运行日志:"
            tail -n 5 "data/logs/${lower_market}_market.log" || true
        else
            echo "   ❌ 报警: ${MARKET} 收集器启动后未正常运行！"
        fi
    fi
done

EOF

echo "==========================================="
echo "🎉 部署与检查流程全部完成！"
echo "==========================================="
