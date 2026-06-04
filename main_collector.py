import os
import json
import time
import sys
import argparse
import queue
import threading
from datetime import datetime
from futu import *

from core.futu_client import FutuTickListener
from core.parquet_engine import ParquetStorageEngine

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# 使用 Python 内置安全中间件解耦 Get-Write 速度差
data_queue = queue.Queue()
stop_event = threading.Event()

def consumer_storage_worker(engine):
    """独立的流式存储消费者线程"""
    print("🧵 Parquet 存储消费者守护线程已拉起...")
    while not stop_event.is_set() or not data_queue.empty():
        try:
            # 阻塞1秒等待数据，防止CPU死循环空空耗
            tick = data_queue.get(timeout=1)
            engine.append_tick(tick['code'], tick)
            data_queue.task_done()
        except queue.Empty:
            continue

def main():
    # 解析命令行参数确定要执行哪一个市场的收集
    parser = argparse.ArgumentParser(description="工业级多市场跨时区高频Tick收集引擎")
    parser.add_argument("--market", required=True, choices=["US", "HK", "CN"], help="指定目标收集市场")
    args = parser.parse_argument_args(sys.argv[1:])
    market = args.market
    
    settings = load_json('./configs/futu_settings.json')
    watchlist = load_json(f'./configs/watchlist_{market.lower()}.json')
    stocks = watchlist["stocks"]
    
    print(f"📡 唤醒收集模块 -> 目标市场: {market} | 监控总标的数量: {len(stocks)}")
    
    # 初始化入库引擎
    storage_engine = ParquetStorageEngine(settings, market)
    
    # 启动存储消费者线程
    storage_thread = threading.Thread(target=consumer_storage_worker, args=(storage_engine,))
    storage_thread.daemon = True
    storage_thread.start()
    
    # 建立富途通道
    quote_ctx = OpenQuoteContext(host=settings["futu_opend"]["host"], port=settings["futu_opend"]["port"])

    # 上传数据到GitHub
    try:
        import subprocess
        repo_path = os.path.dirname(os.path.abspath(__file__))
        os.chdir(repo_path)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"Auto-commit: {datetime.now().isoformat()} - {market} tick data"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"📤 数据已上传至GitHub - {datetime.now()}")
    except Exception as e:
        print(f"⚠️ GitHub上传失败: {e}")
    handler = FutuTickListener(data_queue)
    quote_ctx.set_handler(handler)
    quote_ctx.subscribe(stocks, [SubType.TICKER])
    
    # 设定平稳退出机制
    try:
        while True:
            # 你可以根据三大市场的收盘时间（例如A股15点，港股16点，美股北京时间次日凌晨04点/05点）在这里写退出逻辑
            # 这里保持常态守候，由 crontab 的超时切断或系统信号优雅关闭
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        print("🛑 捕获到终止指令，正在执行优雅停机逻辑...")
    finally:
        quote_ctx.close() # 断开富途
        stop_event.set()  # 通知消费者停止
        storage_thread.join() # 等待消费者把最后的队列写完
        storage_engine.close_all() # 文件封口
        print("🎯 数据收集进程完全安全退出。")

if __name__ == "__main__":
    main()