import os
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime

class ParquetStorageEngine:
    def __init__(self, config, market_type):
        self.config = config
        self.market = market_type.upper()
        self.base_dir = config["storage"]["base_archive_dir"]
        self.flush_threshold = config["storage"]["flush_threshold"]
        self.compression = config["storage"]["compression"]
        
        # 严格定义 Tick 数据的表结构 (Schema)，确保跨市场数据格式绝对对齐
        self.schema = pa.schema([
            ('code', pa.string()),
            ('price', pa.float64()),
            ('volume', pa.int64()),
            ('turnover', pa.float64()),
            ('ticker_direction', pa.string()),
            ('bid_price', pa.float64()),
            ('ask_price', pa.float64())
        ])
        
        # 为每只股票建立独立的内存 Buffer 字典
        self.buffers = {}
        self.writers = {}
        self.today_str = datetime.today().strftime('%Y-%m-%d')
        # 多级目录规划：archive/年/月/市场/股票_日期.parquet
        self.market_dir = os.path.join(self.base_dir, datetime.today().strftime('%Y/%m'), self.market)
        os.makedirs(self.market_dir, exist_ok=True)

    def _init_stock_writer(self, code):
        """为新股票初始化文件指针"""
        self.buffers[code] = []
        file_path = os.path.join(self.market_dir, f"{code}_{self.today_str}.parquet")
        # 打开一个持久化的追加流
        self.writers[code] = pq.ParquetWriter(file_path, self.schema, compression=self.compression)

    def append_tick(self, code, tick_dict):
        """接收单笔数据并进行内存缓冲"""
        if code not in self.buffers:
            self._init_stock_writer(code)
            
        self.buffers[code].append(tick_dict)
        
        # 达到积压阈值，瞬间执行二进制 Row Group 压盘入库
        if len(self.buffers[code]) >= self.flush_threshold:
            self.flush_to_disk(code)

    def flush_to_disk(self, code):
        """将特定股票的内存 Buffer 批量转化为二进制块压入磁盘"""
        if code not in self.buffers or not self.buffers[code]:
            return
            
        df = pd.DataFrame(self.buffers[code])
        # 移除显式索引字段，转为 Table 格式时强制应用统一 Schema
        table = pa.Table.from_pandas(df, schema=self.schema, preserve_index=False)
        self.writers[code].write_table(table)
        
        self.buffers[code].clear() # 瞬间清空内存，防止常驻内存泄漏

    def close_all(self):
        """收盘后，强制将所有剩余尾巴数据刷入磁盘并安全封口指针"""
        print("⚙️ 收到收盘信号，正在将内存残余 Tick 强制固化...")
        for code in list(self.buffers.keys()):
            self.flush_to_disk(code)
            if code in self.writers:
                self.writers[code].close()
        print("🔒 今日所有 Parquet 数据库已安全断开并封口。")