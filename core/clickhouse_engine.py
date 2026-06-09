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
        self.ob_table_name = "order_books"
        self.full_table_path = f"{self.database}.{self.table_name}"
        self.ob_full_table_path = f"{self.database}.{self.ob_table_name}"
        
        # 存储性能设置
        storage_cfg = config["storage"]
        self.flush_threshold = storage_cfg.get("flush_threshold", 1000)
        self.flush_interval_seconds = storage_cfg.get("flush_interval_seconds", 3)
        self.max_buffer_size = 50000  # 安全最大内存缓冲上限
        
        # 建立缓冲与锁
        self.buffer = []
        self.ob_buffer = []
        self.last_flush_time = time.time()
        self.last_ob_flush_time = time.time()
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
        
        # 盘口数据的 Arrow Schema
        self.ob_arrow_schema = pa.schema([
            ('code', pa.string()),
            ('name', pa.string()),
            ('time', pa.timestamp('ms')),
            ('ask_prices', pa.list_(pa.float64())),
            ('ask_volumes', pa.list_(pa.int64())),
            ('ask_orders', pa.list_(pa.int64())),
            ('bid_prices', pa.list_(pa.float64())),
            ('bid_volumes', pa.list_(pa.int64())),
            ('bid_orders', pa.list_(pa.int64()))
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
            
            # 1. 自动建 ticks 表 (使用 MergeTree, 按月分区, (code, time, sequence) 排序)
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
            
            # 2. 自动建 order_books 数组表
            ob_ddl = f"""
            CREATE TABLE IF NOT EXISTS {self.ob_full_table_path} (
                code LowCardinality(String),
                name LowCardinality(String),
                time DateTime64(3, 'Asia/Shanghai'),
                
                ask_prices Array(Float64),
                ask_volumes Array(Int64),
                ask_orders Array(Int64),
                
                bid_prices Array(Float64),
                bid_volumes Array(Int64),
                bid_orders Array(Int64)
            ) ENGINE = MergeTree()
            PARTITION BY toYYYYMM(time)
            ORDER BY (code, time)
            SETTINGS index_granularity = 8192;
            """
            client.command(ob_ddl)
            
            self.client = client
            self.db_connected = True
            logger.info(f"✅ 成功连接 ClickHouse 且库表准备就绪:\n  └─ {self.full_table_path}\n  └─ {self.ob_full_table_path}")
            return True
        except Exception as e:
            self.db_connected = False
            self.client = None
            logger.error(f"❌ 连接 ClickHouse 失败: {e}. 进程将继续收集，数据写入本地灾备目录。")
            return False

    def process_tick(self, tick_dict):
        """解析本地成交时间字符串并将其 localized 赋予对应时区"""
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

    def process_order_book(self, ob_dict):
        """解析买卖盘口时间戳并本地化时区，组装成 ClickHouse Array 格式"""
        # 优先使用富途服务端接收时间
        time_str = ob_dict.get('svr_recv_time_ask') or ob_dict.get('svr_recv_time_bid')
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
            
        code = ob_dict.get('code', '')
        # ⚠️ 修正：富途服务端接收时间 (svr_recv_time) 固定为北京时间(上海时区)
        dt = self.tz_hk.localize(dt)
            
        return {
            'code': code,
            'name': ob_dict.get('name', ''),
            'time': dt,
            'ask_prices': ob_dict.get('ask_prices', []),
            'ask_volumes': ob_dict.get('ask_volumes', []),
            'ask_orders': ob_dict.get('ask_orders', []),
            'bid_prices': ob_dict.get('bid_prices', []),
            'bid_volumes': ob_dict.get('bid_volumes', []),
            'bid_orders': ob_dict.get('bid_orders', [])
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

    def append_order_book(self, code, ob_dict):
        """接收单笔 Order Book，转换格式后写入全局缓冲。必要时触发 Flush。"""
        processed = self.process_order_book(ob_dict)
        
        with self.lock:
            self.ob_buffer.append(processed)
            ob_buffer_len = len(self.ob_buffer)
            
        now = time.time()
        time_elapsed = now - self.last_ob_flush_time
        
        if ob_buffer_len >= self.flush_threshold or (self.flush_interval_seconds > 0 and time_elapsed >= self.flush_interval_seconds):
            self.flush_ob_to_db()

    def flush_to_db(self):
        """同步批量写入 ticks 数据表。网络断开时溢出至本地灾备。"""
        with self.lock:
            if not self.buffer:
                self.last_flush_time = time.time()
                return
            
            temp_buffer = list(self.buffer)
            self.buffer.clear()
            self.last_flush_time = time.time()
            
        success = False
        if self.db_connected and self.client:
            try:
                df = pd.DataFrame(temp_buffer)
                self.client.insert_df(self.full_table_path, df)
                success = True
                del df
                gc.collect()
            except Exception as e:
                logger.error(f"⚠️ 批量插入 ClickHouse Ticks 异常: {e}. 触发灾备本地存储。")
                self.db_connected = False
                self.client = None
                
        # 写入失败，Spill to Disk
        if not success:
            self._spill_to_disk(temp_buffer)
            
        if len(temp_buffer) > 5000:
            gc.collect()

    def flush_ob_to_db(self):
        """同步批量写入 order_books 数据表。网络断开时溢出至本地灾备。"""
        with self.lock:
            if not self.ob_buffer:
                self.last_ob_flush_time = time.time()
                return
            
            temp_buffer = list(self.ob_buffer)
            self.ob_buffer.clear()
            self.last_ob_flush_time = time.time()
            
        success = False
        if self.db_connected and self.client:
            try:
                df = pd.DataFrame(temp_buffer)
                self.client.insert_df(self.ob_full_table_path, df)
                success = True
                del df
                gc.collect()
            except Exception as e:
                logger.error(f"⚠️ 批量插入 ClickHouse OrderBooks 异常: {e}. 触发灾备本地存储。")
                self.db_connected = False
                self.client = None
                
        # 写入失败，Spill to Disk
        if not success:
            self._spill_ob_to_disk(temp_buffer)
            
        if len(temp_buffer) > 5000:
            gc.collect()

    def _spill_to_disk(self, data_list):
        """Ticks 数据溢出到本地临时 Parquet 文件"""
        try:
            ts = int(time.time() * 1000)
            file_name = f"failover_{ts}.parquet"
            file_path = os.path.join(self.failover_dir, file_name)
            
            df = pd.DataFrame(data_list)
            df['time'] = df['time'].apply(lambda x: x.astimezone(pytz.utc).replace(tzinfo=None))
            
            table = pa.Table.from_pandas(df, schema=self.arrow_schema, preserve_index=False)
            pq.write_table(table, file_path)
            
            logger.warning(f"💾 网络异常：已将 {len(data_list)} 条 Ticks 溢出固化至本地灾备: {file_path}")
            del df
            del table
            gc.collect()
        except Exception as ex:
            logger.critical(f"🚨 致命错误：本地 Ticks 灾备溢出写入失败！错误: {ex}", exc_info=True)

    def _spill_ob_to_disk(self, data_list):
        """OrderBook 数据溢出到本地临时 Parquet 文件"""
        try:
            ts = int(time.time() * 1000)
            file_name = f"failover_ob_{ts}.parquet"
            file_path = os.path.join(self.failover_dir, file_name)
            
            df = pd.DataFrame(data_list)
            df['time'] = df['time'].apply(lambda x: x.astimezone(pytz.utc).replace(tzinfo=None))
            
            table = pa.Table.from_pandas(df, schema=self.ob_arrow_schema, preserve_index=False)
            pq.write_table(table, file_path)
            
            logger.warning(f"💾 网络异常：已将 {len(data_list)} 条 OrderBooks 溢出固化至本地灾备: {file_path}")
            del df
            del table
            gc.collect()
        except Exception as ex:
            logger.critical(f"🚨 致命错误：本地 OrderBooks 灾备溢出写入失败！错误: {ex}", exc_info=True)

    def flush_all_stocks(self):
        """被外部消费者周期性/空闲调用以主动刷盘。"""
        self.flush_to_db()
        self.flush_ob_to_db()

    def _recovery_worker(self):
        """后台重连与双表灾备数据恢复线程"""
        retry_interval = 5
        while not self.stop_event.is_set():
            # 1. 检查并重连主数据库连接
            if not self.db_connected or not self.client:
                self.connect_db()
                if not self.db_connected:
                    time.sleep(retry_interval)
                    retry_interval = min(retry_interval * 2, 60)
                    continue
                else:
                    retry_interval = 5
            
            # 2. 如果主连接正常，独立实例化一个 recovery_client 用于回放积压的本地 failover 文件
            recovery_client = None
            try:
                tick_files = sorted([f for f in os.listdir(self.failover_dir) if f.startswith("failover_") and not f.startswith("failover_ob_") and f.endswith(".parquet")])
                ob_files = sorted([f for f in os.listdir(self.failover_dir) if f.startswith("failover_ob_") and f.endswith(".parquet")])
                
                if tick_files or ob_files:
                    recovery_client = clickhouse_connect.get_client(
                        host=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password
                    )
                    
                    # 2.1 恢复 Ticks
                    if tick_files:
                        logger.info(f"⏳ 发现 {len(tick_files)} 个 Ticks 故障灾备数据块，启动异步补录...")
                        for fname in tick_files:
                            if self.stop_event.is_set():
                                break
                            file_path = os.path.join(self.failover_dir, fname)
                            try:
                                df = pd.read_parquet(file_path)
                                def re_localize_tick(row):
                                    code = row['code']
                                    dt_utc = pytz.utc.localize(row['time'])
                                    if '.US' in code or code.startswith('US.'):
                                        return dt_utc.astimezone(self.tz_us)
                                    else:
                                        return dt_utc.astimezone(self.tz_hk)
                                df['time'] = df.apply(re_localize_tick, axis=1)
                                recovery_client.insert_df(self.full_table_path, df)
                                logger.info(f"⚡ 成功补录 Ticks 数据块 {fname} ({len(df)} 条) 到 ClickHouse")
                                os.remove(file_path)
                                del df
                                gc.collect()
                            except Exception as block_ex:
                                logger.error(f"❌ 补录 Ticks 数据块 {fname} 失败: {block_ex}. 稍后重试。")
                                break
                    
                    # 2.2 恢复 OrderBooks
                    if ob_files:
                        logger.info(f"⏳ 发现 {len(ob_files)} 个 OrderBooks 故障灾备数据块，启动异步补录...")
                        for fname in ob_files:
                            if self.stop_event.is_set():
                                break
                            file_path = os.path.join(self.failover_dir, fname)
                            try:
                                df = pd.read_parquet(file_path)
                                def re_localize_ob(row):
                                    dt_utc = pytz.utc.localize(row['time'])
                                    return dt_utc.astimezone(self.tz_hk)
                                df['time'] = df.apply(re_localize_ob, axis=1)
                                recovery_client.insert_df(self.ob_full_table_path, df)
                                logger.info(f"⚡ 成功补录 OrderBooks 数据块 {fname} ({len(df)} 条) 到 ClickHouse")
                                os.remove(file_path)
                                del df
                                gc.collect()
                            except Exception as block_ex:
                                logger.error(f"❌ 补录 OrderBooks 数据块 {fname} 失败: {block_ex}. 稍后重试。")
                                break
                                
            except Exception as loop_ex:
                logger.error(f"⚠️ 补录守护进程发生未知异常: {loop_ex}")
            finally:
                if recovery_client:
                    try:
                        recovery_client.close()
                    except Exception:
                        pass
                
            time.sleep(5)

    def close_all(self):
        """优雅关闭：强制执行同步刷盘，关闭连接，停止后台线程"""
        logger.info("⚙️ 收到收盘信号，关闭 ClickHouse 存储引擎...")
        
        # 1. 停止恢复后台线程
        self.stop_event.set()
        if self.recovery_thread.is_alive():
            self.recovery_thread.join(timeout=3)
            
        # 2. 强制将所有缓冲区残留数据同步写入
        self.flush_to_db()
        self.flush_ob_to_db()
        
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
            self.ob_buffer.clear()
            
        gc.collect()
        logger.info("🔒 ClickHouse 存储引擎完全安全退出。")
