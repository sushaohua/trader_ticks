#!/usr/bin/env python3
"""
内存监控守护进程 - 防止OOM导致系统死机

监视data_collector进程的内存占用，超过阈值时：
1. 记录警告日志
2. 主动杀死进程，触发重启
3. 防止内存占用持续增长
"""

import os
import sys
import time
import subprocess
import logging
import atexit
from datetime import datetime

# 配置日志
LOG_DIR = os.path.join(os.path.dirname(__file__), 'data', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 🔥 修复：正确管理日志句柄
log_file_path = os.path.join(LOG_DIR, 'memory_monitor.log')
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))

logger = logging.getLogger(__name__)
logger.addHandler(file_handler)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

def cleanup_handlers():
    """清理日志句柄 - 确保优雅关闭"""
    for handler in logger.handlers[:]:  # 遍历副本以安全删除
        try:
            handler.close()
            logger.removeHandler(handler)
        except Exception:
            pass

# 注册退出处理器
atexit.register(cleanup_handlers)

# 内存阈值配置 (MB)
MEMORY_WARNING_THRESHOLD = 2000    # 超过2GB时发出警告
MEMORY_KILL_THRESHOLD = 3500       # 超过3.5GB时强制杀死进程
MEMORY_CHECK_INTERVAL = 60         # 每60秒检查一次

def get_process_memory(pid):
    """获取进程内存占用 (MB)"""
    try:
        with open(f'/proc/{pid}/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    # VmRSS 是实际物理内存占用 (单位: kB)
                    rss_kb = int(line.split()[1])
                    return rss_kb / 1024  # 转换为 MB
        return 0
    except (FileNotFoundError, ValueError):
        return 0

def get_collector_pids(market):
    """获取指定市场的收集器PID"""
    pid_file = os.path.join(LOG_DIR, f'{market.lower()}_collector.pid')
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            return None
    return None

def is_process_alive(pid):
    """检查进程是否存活"""
    try:
        os.kill(pid, 0)  # 不发送信号，只检查权限
        return True
    except (OSError, ProcessLookupError):
        return False

def kill_process(pid, market):
    """杀死进程并记录"""
    try:
        logger.warning(f"🔴 杀死 {market} 收集器进程 (PID {pid})，防止OOM")
        os.kill(pid, 9)  # SIGKILL
        time.sleep(2)
        if is_process_alive(pid):
            logger.error(f"❌ 无法杀死进程 {pid}")
            return False
        else:
            logger.info(f"✅ 已成功杀死进程 {pid}")
            return True
    except (OSError, ProcessLookupError) as e:
        logger.error(f"❌ 杀死进程失败: {e}")
        return False

def monitor_memory():
    """主监控循环"""
    logger.info("🚀 内存监控守护进程启动")
    logger.info(f"⚙️ 警告阈值: {MEMORY_WARNING_THRESHOLD}MB, 杀死阈值: {MEMORY_KILL_THRESHOLD}MB")
    
    markets = ['HK', 'US', 'CN']
    
    while True:
        try:
            for market in markets:
                pid = get_collector_pids(market)
                
                if pid is None:
                    # logger.debug(f"❓ {market} 收集器未运行")
                    continue
                
                if not is_process_alive(pid):
                    logger.warning(f"⚠️ {market} 收集器进程已终止 (PID {pid})")
                    continue
                
                memory_mb = get_process_memory(pid)
                
                if memory_mb <= 0:
                    logger.warning(f"⚠️ 无法读取 {market} 进程内存 (PID {pid})")
                    continue
                
                # 记录日志
                if memory_mb > MEMORY_KILL_THRESHOLD:
                    logger.critical(
                        f"🔴 {market} 收集器内存超限: {memory_mb:.0f}MB > {MEMORY_KILL_THRESHOLD}MB"
                    )
                    kill_process(pid, market)
                    
                elif memory_mb > MEMORY_WARNING_THRESHOLD:
                    logger.warning(
                        f"⚠️ {market} 收集器内存较高: {memory_mb:.0f}MB (>= {MEMORY_WARNING_THRESHOLD}MB)"
                    )
                else:
                    logger.info(
                        f"✅ {market} 收集器内存正常: {memory_mb:.0f}MB"
                    )
            
            time.sleep(MEMORY_CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ 监控线程异常: {e}")
            time.sleep(MEMORY_CHECK_INTERVAL)

if __name__ == '__main__':
    try:
        monitor_memory()
    except KeyboardInterrupt:
        logger.info("🛑 内存监控进程已停止")
        sys.exit(0)
