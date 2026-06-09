import os
import gc
import time
import queue
import threading
import logging
from datetime import datetime
import pytz
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import clickhouse_connect

logger = logging.getLogger(__name__)

class ClickHouseStorageEngine:
    def __init__(self, config, market_type):
        self.config = config
        self.market = market_type.upper()
        
        # 加载 ClickHouse 配置
        ch_cfg = config["clickhouse"]
        self.host = ch_cfg["host"]
        self.port = int(ch_cfg["port"])
        self.username = ch_cfg["username"]
        self.password = ch_cfg["password"]
        self.database = ch_cfg.get("database", "stock_preview")
        self.table_name = "ticks"
        self.full_table_path = f"{self.database}.{self.table_name}"
        
        # 存储性能设置
        storage_cfg = config["storage"]
        self.flush_threshold = storage_cfg.get("flush_threshold", 1000)
        self.flush_interval_seconds = storage_cfg.get("flush_interval_seconds", 3)
        self.max_buffer_size = 50000  # 安全最大内存缓冲上限，防止 OOM
        
        # 建立缓冲与锁
        self.buffer = []
        self.last_flush_time = time.time()
        self.lock = threading.Lock()
        
        # 灾备路径配置
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.failover_dir = os.path.join(project_root, "data", "clickhouse_failover")
        os.makedirs(self.failover_dir, exist_ok=True)
        
        # 严格定义 Arrow Schema 用于本地灾备写入
        self.arrow_schema = pa.schema([
            ('code', pa.string()),
            ('name', pa.string()),
            ('time', pa.timestamp('ms')),
            ('price', pa.float64()),
            ('volume', pa.int64()),
            ('turnover', pa.float64()),
            ('ticker_direction', pa.string()),
            ('sequence', pa.int64()),
            ('type', pa.string()),
            ('push_data_type', pa.string())
        ])
        
        # 初始化时区
        self.tz_hk = pytz.timezone('Asia/Shanghai')
        self.tz_us = pytz.timezone('America/New_York')
        
        # 状态变量
        self.client = None
        self.db_connected = False
        
        # 线程控制
        self.stop_event = threading.Event()
        
        # 尝试第一次连接数据库并初始化建库建表
        self.connect_db()
        
        # 启动后台守护线程：负责重连及历史灾备数据异步补录
        self.recovery_thread = threading.Thread(target=self._recovery_worker, name="CHRecoveryThread")
        self.recovery_thread.daemon = True
        self.recovery_thread.start()

    def connect_db(self):
        """尝试连接 ClickHouse 数据库并创建对应的库表"""
        try:
            client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password
            )
            # 自动建库
            client.command(f"CREATE DATABASE IF NOT EXISTS {self.database}")
            
            # 自动建表 (使用 MergeTree, 按月分区, (code, time, sequence) 排序)
            ddl = f"""
            CREATE TABLE IF NOT EXISTS {self.full_table_path} (
                code LowCardinality(String),
                name LowCardinality(String),
                time DateTime64(3, 'Asia/Shanghai'),
                price Float64,
                volume Int64,
                turnover Float64,
                ticker_direction LowCardinality(String),
                sequence Int64,
                type LowCardinality(String),
                push_data_type LowCardinality(String)
            ) ENGINE = MergeTree()
            PARTITION BY toYYYYMM(time)
            ORDER BY (code, time, sequence)
            SETTINGS index_granularity = 8192;
            """
            client.command(ddl)
            
            self.client = client
            self.db_connected = True
            logger.info(f"✅ 成功连接 ClickHouse 且库表准备就绪: {self.full_table_path}")
            return True
        except Exception as e:
            self.db_connected = False
            self.client = None
            logger.error(f"❌ 连接 ClickHouse 失败: {e}. 进程将继续收集，数据写入本地灾备目录。")
            return False

    def process_tick(self, tick_dict):
        """解析本地时间字符串并将其 localized 赋予对应时区"""
        time_str = tick_dict.get('time', '')
        if time_str:
            try:
                dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                try:
                    dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    dt = datetime.now()
        else:
            dt = datetime.now()
            
        code = tick_dict.get('code', '')
        
        # 区分美股和港/A股时区
        if '.US' in code or code.startswith('US.'):
            dt = self.tz_us.localize(dt)
        else:
            dt = self.tz_hk.localize(dt)
            
        return {
            'code': code,
            'name': tick_dict.get('name', ''),
            'time': dt,  # 带时区的 datetime，驱动写入时会自动将其对齐为 UTC
            'price': float(tick_dict.get('price', 0.0)),
            'volume': int(tick_dict.get('volume', 0)),
            'turnover': float(tick_dict.get('turnover', 0.0)),
            'ticker_direction': tick_dict.get('ticker_direction', 'NEUTRAL'),
            'sequence': int(tick_dict.get('sequence', 0)),
            'type': tick_dict.get('type', ''),
            'push_data_type': tick_dict.get('push_data_type', '')
        }

    def append_tick(self, code, tick_dict):
        """接收单笔 Tick，转换格式后写入全局缓冲。必要时触发 Flush。"""
        processed = self.process_tick(tick_dict)
        
        with self.lock:
            self.buffer.append(processed)
            buffer_len = len(self.buffer)
            
        now = time.time()
        time_elapsed = now - self.last_flush_time
        
        # 达到阈值，或者超时
        if buffer_len >= self.flush_threshold or (self.flush_interval_seconds > 0 and time_elapsed >= self.flush_interval_seconds):
            self.flush_to_db()

    def flush_to_db(self):
        """同步批量写入 ClickHouse 数据库。网络断开时溢出至本地灾备。"""
        with self.lock:
            if not self.buffer:
                self.last_flush_time = time.time()
                return
            
            temp_buffer = list(self.buffer)
            self.buffer.clear()
            self.last_flush_time = time.time()
            
        # 开始尝试写入 ClickHouse
        success = False
        if self.db_connected and self.client:
            try:
                df = pd.DataFrame(temp_buffer)
                
                # 显式转换时间字段类型，确保与 clickhouse_connect 匹配
                # 并且不保留 index
                self.client.insert_df(self.full_table_path, df)
                success = True
                
                # 显式清理内存，防范内存泄露
                del df
                gc.collect()
            except Exception as e:
                logger.error(f"⚠️ 批量插入 ClickHouse 异常: {e}. 触发灾备本地存储。")
                self.db_connected = False
                self.client = None
                
        # 写入失败或本身处于断开状态，启动 Failover Spill to Disk
        if not success:
            self._spill_to_disk(temp_buffer)
            
        # 如果当前累积的 buffer 太大，强制二次垃圾回收
        if len(temp_buffer) > 5000:
            gc.collect()

    def _spill_to_disk(self, data_list):
        """数据溢出到本地临时 Parquet 文件"""
        try:
            ts = int(time.time() * 1000)
            file_name = f"failover_{ts}.parquet"
            file_path = os.path.join(self.failover_dir, file_name)
            
            df = pd.DataFrame(data_list)
            # 在写入本地 parquet 前，需要把 datetime 带时区对象统一转换为不带时区的 UTC datetime
            # pyarrow 对 timestamp('ms') 配合带 timezone 的 pd.Series 转换可能会有兼容性警告，
            # 我们显式地在 DataFrame 里先转换为 numpy datetime64
            df['time'] = df['time'].apply(lambda x: x.astimezone(pytz.utc).replace(tzinfo=None))
            
            table = pa.Table.from_pandas(df, schema=self.arrow_schema, preserve_index=False)
            pq.write_table(table, file_path)
            
            logger.warning(f"💾 网络断开/异常：已将 {len(data_list)} 条数据溢出固化至本地灾备文件: {file_path}")
            
            del df
            del table
            gc.collect()
        except Exception as ex:
            logger.critical(f"🚨 致命错误：本地灾备溢出写入失败！数据将丢失！错误: {ex}", exc_info=True)

    def flush_all_stocks(self):
        """被外部消费者周期性/空闲调用以主动刷盘。"""
        self.flush_to_db()

    def _recovery_worker(self):
        """后台重连与灾备数据恢复线程"""
        retry_interval = 5
        while not self.stop_event.is_set():
            # 1. 检查并重连数据库
            if not self.db_connected or not self.client:
                # 逐步增加重连间隔
                self.connect_db()
                if not self.db_connected:
                    time.sleep(retry_interval)
                    retry_interval = min(retry_interval * 2, 60) # 最长60秒重试一次
                    continue
                else:
                    retry_interval = 5
            
            # 2. 如果重连成功，扫描灾备 Parquet 并尝试恢复
            try:
                files = sorted([f for f in os.listdir(self.failover_dir) if f.startswith("failover_") and f.endswith(".parquet")])
                if files:
                    logger.info(f"⏳ 发现 {len(files)} 个历史网络故障灾备数据块，启动异步补录...")
                    
                    for fname in files:
                        if self.stop_event.is_set():
                            break
                            
                        file_path = os.path.join(self.failover_dir, fname)
                        try:
                            # 读取 parquet 并写入 ClickHouse
                            df = pd.read_parquet(file_path)
                            
                            # 读取出来的 datetime 需要重新 localized 赋值，因为 parquet 存的是 naive UTC
                            # clickhouse-connect 插入时需要带时区
                            def re_localize(row):
                                code = row['code']
                                # df 读取出来是 UTC，我们先赋予 UTC，然后转换为各自本土时区
                                dt_utc = pytz.utc.localize(row['time'])
                                if '.US' in code or code.startswith('US.'):
                                    return dt_utc.astimezone(self.tz_us)
                                else:
                                    return dt_utc.astimezone(self.tz_hk)
                                    
                            df['time'] = df.apply(re_localize, axis=1)
                            
                            self.client.insert_df(self.full_table_path, df)
                            logger.info(f"⚡ 成功补录数据块 {fname} ({len(df)} 条) 到 ClickHouse")
                            
                            # 写入成功后删除物理文件
                            os.remove(file_path)
                            
                            del df
                            gc.collect()
                        except Exception as block_ex:
                            logger.error(f"❌ 补录数据块 {fname} 失败: {block_ex}. 稍后重试。")
                            break # 单个块失败，暂停本次补录循环
            except Exception as loop_ex:
                logger.error(f"⚠️ 补录守护进程发生未知异常: {loop_ex}")
                
            # 心跳检查，隔5秒扫描一次
            time.sleep(5)

    def close_all(self):
        """优雅关闭：强制执行同步刷盘，关闭连接，停止后台线程"""
        logger.info("⚙️ 收到收盘信号，关闭 ClickHouse 存储引擎...")
        
        # 1. 停止重连/恢复后台线程
        self.stop_event.set()
        if self.recovery_thread.is_alive():
            self.recovery_thread.join(timeout=3)
            
        # 2. 强制将缓冲区残留数据写入
        self.flush_to_db()
        
        # 3. 断开 ClickHouse 物理连接
        if self.client:
            try:
                self.client.close()
                logger.info("🔌 ClickHouse 连接已安全释放。")
            except Exception as e:
                logger.error(f"断开 ClickHouse 异常: {e}")
                
        self.db_connected = False
        self.client = None
        
        with self.lock:
            self.buffer.clear()
            
        gc.collect()
        logger.info("🔒 ClickHouse 存储引擎完全安全退出。")
