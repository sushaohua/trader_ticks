#!/usr/bin/env bash

set -e

# 获取脚本所在项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🔍 开始本地开发环境自动验证..."
echo "项目根目录: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

# 确定虚拟环境 Python
if [ -f "venv/bin/python" ]; then
    PYTHON_EXEC="venv/bin/python"
elif [ -f "venv/bin/python3" ]; then
    PYTHON_EXEC="venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

echo "==========================================="
echo "🧪 1. 运行核心业务冒烟测试 (unittest)..."
echo "==========================================="

if $PYTHON_EXEC -m unittest tests/test_smoke.py; then
    echo "✅ 核心逻辑冒烟测试通过！"
else
    echo "❌ 核心逻辑冒烟测试失败，请排查逻辑错误！"
    exit 1
fi

echo "==========================================="
echo "🔌 2. 测试本地 Futu OpenD 连接健康状况..."
echo "==========================================="

$PYTHON_EXEC -c "
import sys
import os
try:
    from futu import *
    if not os.path.exists('configs/futu_settings.json'):
        print('      ❌ 软链接未建立或找不到 configs/futu_settings.json！请先运行 scripts/setup_config.sh')
        sys.exit(1)
        
    from core.config import load_config
    cfg = load_config()
    host = cfg['futu_opend']['host']
    port = cfg['futu_opend']['port']
    print(f'   -> 正在尝试连接本地 OpenD ({host}:{port})...')
    
    q = OpenQuoteContext(host=host, port=port)
    ret, state = q.get_global_state()
    q.close()
    if ret == 0:
        is_logined = state.get('login_status') == '1' or state.get('qot_logined') is True
        if is_logined:
            print('      ✅ OpenD 状态检查通过: 本地连接就绪，已成功登录富途服务器。')
            print(f'      详细状态: {state}')
        else:
            print('      ⚠️ OpenD 状态检查警告: 连接成功但未登录服务器。详情: ', state)
    else:
        print('      ❌ OpenD 状态检查失败 (接口返回错误): ', ret, state)
        sys.exit(1)
except Exception as e:
    print('      ❌ 无法连接本地 OpenD，请确认 Futu OpenD 是否已在本地开启: ', e)
    sys.exit(1)
"

echo "==========================================="
echo "🎉 本地自动验证流程全部完成，一切就绪！"
echo "==========================================="
