import os
import json
import time
import gc
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
    gc_interval = 0
    empty_count = 0  # 🔥 添加空队列计数，用于优化刷盘
    
    while not stop_event.is_set() or not data_queue.empty():
        try:
            # 阻塞1秒等待数据，防止CPU死循环空空耗
            tick = data_queue.get(timeout=1)
            empty_count = 0  # 重置空计数
            engine.append_tick(tick['code'], tick)
            data_queue.task_done()
            
            # 🔥 周期性垃圾回收（每处理1000条数据触发一次）
            gc_interval += 1
            if gc_interval % 1000 == 0:
                gc.collect()  # 防止临时对象积累
        except queue.Empty:
            # 🔥 改进：连续多次空队列后，主动刷盘未提交的数据
            empty_count += 1
            if empty_count % 3 == 0:  # 每3次空循环尝试一次刷盘
                engine.flush_all_stocks()  # 刷盘所有未提交的数据
            continue

def main():
    # 解析命令行参数确定要执行哪一个市场的收集
    parser = argparse.ArgumentParser(description="工业级多市场跨时区高频Tick收集引擎")
    parser.add_argument("--market", required=True, choices=["US", "HK", "CN"], help="指定目标收集市场")
    args = parser.parse_args()
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

    handler = FutuTickListener(data_queue)
    quote_ctx.set_handler(handler)
    
    # 🔥 添加连接重试限制，防止无限重试导致内存爆炸
    max_retries = 100  # 最多重试100次
    retry_count = 0
    subscribe_success = False
    
    while retry_count < max_retries:
        try:
            quote_ctx.subscribe(stocks, [SubType.TICKER])
            print(f"✅ 成功订阅 {len(stocks)} 只股票")
            subscribe_success = True
            break
        except Exception as e:
            retry_count += 1
            if retry_count >= max_retries:
                print(f"❌ 订阅失败，已达到最大重试次数({max_retries})，进程退出")
                # 🔥 修复：使用异常而非 exit()，确保 finally 块执行
                raise RuntimeError(f"无法订阅股票，已尝试 {max_retries} 次: {e}")
            print(f"⚠️ 订阅失败(重试 {retry_count}/{max_retries}): {e}")
            time.sleep(5)  # 等待5秒后重试
    
    if not subscribe_success:
        raise RuntimeError("订阅股票失败")
    
    # 设定平稳退出机制
    try:
        while True:
            # 你可以根据三大市场的收盘时间（例如A股15点，港股16点，美股北京时间次日凌晨04点/05点）在这里写退出逻辑
            # 这里保持常态守候，由 crontab 的超时切断或系统信号优雅关闭
            time.sleep(10)
            
            # 🔥 定期垃圾回收（每10秒检查一次）
            if data_queue.empty():
                gc.collect()
    except (KeyboardInterrupt, SystemExit):
        print("🛑 捕获到终止指令，正在执行优雅停机逻辑...")
    finally:
        quote_ctx.close() # 断开富途
        stop_event.set()  # 通知消费者停止
        storage_thread.join(timeout=10) # 等待消费者把最后的队列写完（最多等待10秒）
        storage_engine.close_all() # 文件封口
        
        # 🔥 最后的清理：显式释放大对象和垃圾回收
        del quote_ctx
        del handler
        del storage_engine
        del storage_thread
        gc.collect()  # 最后的垃圾回收
        
        print("🎯 数据收集进程完全安全退出。")

if __name__ == "__main__":
    main()