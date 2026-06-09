import os
import sys
import time
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import datetime
import pytz
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# 解析项目根路径以正确导入模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.clickhouse_engine import ClickHouseStorageEngine

class TestClickHouseEngine(unittest.TestCase):
    def setUp(self):
        # 创建标准的模拟配置
        self.config = {
            "clickhouse": {
                "host": "103.118.254.69",
                "port": 8123,
                "username": "sushaohua",
                "password": "7758521.aA",
                "database": "stock_preview"
            },
            "storage": {
                "engine": "clickhouse",
                "flush_threshold": 3,
                "flush_interval_seconds": 2,
                "compression": "snappy"
            }
        }
        
    def test_timezone_parsing(self):
        """测试不同市场的 Tick 时间戳时区解析是否正确"""
        # 我们在这里不需要物理连接数据库，可以 mock connect_db 和 _recovery_worker
        with mock.patch.object(ClickHouseStorageEngine, 'connect_db', return_value=True):
            with mock.patch.object(ClickHouseStorageEngine, '_recovery_worker', return_value=None):
                engine = ClickHouseStorageEngine(self.config, "HK")
                
                # 1. 港股测试 (北京时间 Asia/Shanghai)
                hk_tick = {
                    "code": "HK.00700",
                    "time": "2026-06-09 16:00:00.123",
                    "price": 450.0,
                    "volume": 100
                }
                processed_hk = engine.process_tick(hk_tick)
                self.assertEqual(processed_hk['time'].tzinfo.zone, 'Asia/Shanghai')
                self.assertEqual(processed_hk['time'].hour, 16)
                self.assertEqual(processed_hk['time'].minute, 0)
                
                # 2. 美股测试 (美东时间 America/New_York)
                us_tick = {
                    "code": "US.AAPL",
                    "time": "2026-06-09 09:30:00.500",
                    "price": 180.0,
                    "volume": 200
                }
                processed_us = engine.process_tick(us_tick)
                self.assertEqual(processed_us['time'].tzinfo.zone, 'America/New_York')
                self.assertEqual(processed_us['time'].hour, 9)
                self.assertEqual(processed_us['time'].minute, 30)

    def test_spill_to_disk_on_failure(self):
        """测试 ClickHouse 写入失败时，数据是否能正确溢出到本地灾备"""
        with mock.patch.object(ClickHouseStorageEngine, 'connect_db', return_value=True):
            with mock.patch.object(ClickHouseStorageEngine, '_recovery_worker', return_value=None):
                # 临时创建一个灾备目录，避免污染真实数据
                temp_failover_dir = tempfile.mkdtemp()
                
                engine = ClickHouseStorageEngine(self.config, "HK")
                # 替换为临时灾备路径
                engine.failover_dir = temp_failover_dir
                
                # 模拟数据库断开
                engine.db_connected = False
                engine.client = None
                
                # 填充数据
                tick1 = {"code": "HK.00700", "time": "2026-06-09 16:00:01.000", "price": 450.0}
                tick2 = {"code": "HK.00700", "time": "2026-06-09 16:00:02.000", "price": 451.0}
                tick3 = {"code": "HK.00700", "time": "2026-06-09 16:00:03.000", "price": 452.0}
                
                # 触发 append，由于 threshold=3，在第三次 append 后应该自动触发 flush_to_db 并因为 db_connected=False 写入本地
                engine.append_tick("HK.00700", tick1)
                engine.append_tick("HK.00700", tick2)
                engine.append_tick("HK.00700", tick3)
                
                # 检查临时目录是否生成了 failover_*.parquet 文件
                files = os.listdir(temp_failover_dir)
                self.assertTrue(any(f.startswith("failover_") and f.endswith(".parquet") for f in files))
                
                # 读取生成的临时 parquet，校验数据一致性
                parquet_file = os.path.join(temp_failover_dir, files[0])
                df = pd.read_parquet(parquet_file)
                self.assertEqual(len(df), 3)
                self.assertEqual(df.iloc[0]['code'], "HK.00700")
                self.assertEqual(df.iloc[2]['price'], 452.0)
                
                # 清理临时目录
                shutil.rmtree(temp_failover_dir, ignore_errors=True)

    @unittest.skipIf(os.environ.get("SKIP_INTEGRATION_TESTS"), "跳过 ClickHouse 集成测试")
    def test_database_integration(self):
        """真实的 ClickHouse 写入集成测试 (如果网络通畅则运行)"""
        # 测试与真实 ClickHouse 的交互
        engine = ClickHouseStorageEngine(self.config, "HK")
        if not engine.db_connected:
            self.skipTest("ClickHouse 数据库不可达，跳过集成写入测试。")
            
        try:
            # 先清空或保证测试表存在，插入测试 Tick
            test_seq = int(time.time() * 1000)
            tick = {
                "code": "HK.TEST_UNIT",
                "name": "TEST_STK",
                "time": "2026-06-09 10:00:00.123",
                "price": 10.5,
                "volume": 500,
                "turnover": 5250.0,
                "ticker_direction": "BUY",
                "sequence": test_seq,
                "type": "NORMAL",
                "push_data_type": "REALTIME"
            }
            
            # 手动执行一次同步写入
            engine.append_tick("HK.TEST_UNIT", tick)
            engine.flush_to_db()
            
            # 查回该测试数据并验证
            res = engine.client.query(f"SELECT * FROM {engine.full_table_path} WHERE code = 'HK.TEST_UNIT' AND sequence = {test_seq}").result_rows
            self.assertEqual(len(res), 1)
            row = res[0]
            # 索引映射：
            # code=0, name=1, time=2, price=3, volume=4, turnover=5, ticker_direction=6, sequence=7, type=8, push_data_type=9
            self.assertEqual(row[0], "HK.TEST_UNIT")
            self.assertEqual(row[1], "TEST_STK")
            self.assertEqual(row[3], 10.5)
            self.assertEqual(row[4], 500)
            self.assertEqual(row[7], test_seq)
            
            # 清理测试行
            engine.client.command(f"ALTER TABLE {engine.full_table_path} DELETE WHERE code = 'HK.TEST_UNIT'")
        finally:
            engine.close_all()

if __name__ == "__main__":
    unittest.main()
